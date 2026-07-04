"""Motor XTTS-v2 (coqui-tts) — alternativa ao Chatterbox.

Mesmo contrato do TTSEngine (synthesize/ensure_loaded/loaded/empty_cache/
_reload_locked), saída WAV 24 kHz mono. Usa um FALANTE EMBUTIDO (ex.: "Ana
Florence"), então NÃO precisa de áudio de referência.

Vantagem prática: ~2 GB de VRAM (vs ~5.6 GB do Chatterbox) → muito menos
pressão numa placa de 8 GB compartilhada, o que evita o travamento por erro
de CUDA/VRAM na pré-geração de livros grandes.
"""
from __future__ import annotations

import os
import re
import threading

import numpy as np

from backend.config import XTTS_SPEAKER
from backend.tts.engine import (
    SAMPLE_RATE,
    _empty_cache,
    _sanitize_text,
    _silence_wav,
    _to_mono_float,
    _trim_audio,
    _tune_perf,
    _wav_bytes_from_array,
    detect_hardware,
)
from backend.tts.voices import DEFAULT_VOICE_ID, resolve_voice
from backend.utils.logging import get_logger

logger = get_logger("tts.xtts")

MODEL_ID = "tts_models/multilingual/multi-dataset/xtts_v2"

# O XTTS "viaja" (repete/inventa fala) quando recebe um trecho muito longo de
# uma vez. Fatiamos em blocos curtos e sintetizamos um a um — cada geração fica
# limitada, o que (1) evita a leitura sem sentido e (2) reduz o risco de travar,
# já que nenhuma chamada isolada fica gigante.
_MAX_CHUNK_CHARS = 220
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+")


def _hard_wrap(text: str, limit: int) -> list[str]:
    """Último recurso: quebra por palavras quando nem uma oração cabe no limite."""
    out: list[str] = []
    cur = ""
    for word in text.split(" "):
        if not word:
            continue
        if cur and len(cur) + 1 + len(word) > limit:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


def _chunk_text(text: str, limit: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Divide o texto em blocos <= limit, respeitando frases, depois orações
    (vírgula/;/:) e, no pior caso, palavras. Nunca corta no meio de uma palavra."""
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []

    units: list[str] = []
    for sent in _SENT_SPLIT.split(text):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= limit:
            units.append(sent)
            continue
        for clause in _CLAUSE_SPLIT.split(sent):
            clause = clause.strip()
            if not clause:
                continue
            if len(clause) <= limit:
                units.append(clause)
            else:
                units.extend(_hard_wrap(clause, limit))

    # Junta unidades vizinhas enquanto couber (menos chamadas = mais rápido).
    chunks: list[str] = []
    cur = ""
    for u in units:
        if cur and len(cur) + 1 + len(u) > limit:
            chunks.append(cur)
            cur = u
        else:
            cur = f"{cur} {u}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _guard_ramble(arr: np.ndarray, text: str) -> np.ndarray:
    """Rede de segurança: se o áudio ficou absurdamente mais longo do que o texto
    justifica (o XTTS entrou em loop/alucinação), apara para um teto plausível em
    vez de reproduzir minutos de fala inventada."""
    if arr.size == 0:
        return arr
    dur = arr.size / SAMPLE_RATE
    nchars = max(1, sum(ch.isalpha() for ch in text))
    expected = nchars / 12.0 + 0.6  # ~12 letras faladas por segundo + folga
    if dur > expected * 3.0 and dur > 7.0:
        cap = int(SAMPLE_RATE * max(expected * 1.8, 3.0))
        if cap < arr.size:
            logger.warning(
                "XTTS possível 'ramble' (%.1fs p/ %d letras) — aparando p/ %.1fs",
                dur, nchars, cap / SAMPLE_RATE,
            )
            return arr[:cap]
    return arr


def _install_transformers_shim() -> None:
    """O transformers 5.x removeu isin_mps_friendly, que o XTTS ainda importa.
    Repõe um equivalente (torch.isin) — sem isso o import/inferência quebram."""
    try:
        import torch
        import transformers.pytorch_utils as tpu

        if not hasattr(tpu, "isin_mps_friendly"):
            tpu.isin_mps_friendly = lambda elements, test_elements: torch.isin(
                elements, test_elements
            )
    except Exception:
        logger.exception("Falha ao aplicar shim do transformers")


class XTTSEngine:
    """Lazy wrapper do XTTS-v2 (coqui-tts) com voz pt-BR embutida."""

    def __init__(self) -> None:
        self.hardware = detect_hardware()
        self._tts = None
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()
        self._load_error: str | None = None
        self._speaker = XTTS_SPEAKER

    @property
    def loaded(self) -> bool:
        return self._tts is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def ensure_loaded(self) -> None:
        if self._tts is not None:
            return
        with self._lock:
            if self._tts is not None:
                return
            try:
                os.environ.setdefault("COQUI_TOS_AGREED", "1")  # licença sem prompt
                _install_transformers_shim()
                _tune_perf()
                from TTS.api import TTS  # import pesado

                device = "cuda" if self.hardware.cuda_available else "cpu"
                logger.info("Carregando XTTS-v2 (device=%s, speaker=%s)", device, self._speaker)
                self._tts = TTS(MODEL_ID).to(device)
                spks = self._speakers()
                if spks and self._speaker not in spks:
                    logger.warning("Speaker %r inexistente; usando %r", self._speaker, spks[0])
                    self._speaker = spks[0]
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Falha ao carregar XTTS-v2")
                raise

    def _speakers(self) -> list[str]:
        try:
            return list(self._tts.synthesizer.tts_model.speaker_manager.speakers.keys())
        except Exception:
            try:
                return list(self._tts.speakers or [])
            except Exception:
                return []

    def _tts_once(self, text: str, speaker: str) -> np.ndarray:
        import torch

        # repetition_penalty alto + top_k/top_p contêm o "rambling" (o XTTS às
        # vezes repete/estende demais). Também deixa a geração mais rápida.
        with torch.inference_mode():
            wav = self._tts.tts(
                text=text,
                speaker=speaker,
                language="pt",
                split_sentences=False,  # já fatiamos nós mesmos, em blocos curtos
                temperature=0.7,
                repetition_penalty=5.0,
                length_penalty=1.0,
                top_k=50,
                top_p=0.85,
            )
        return _guard_ramble(_to_mono_float(wav), text)

    def _generate(self, clean: str, speaker: str) -> np.ndarray:
        """Fatia o texto em blocos curtos, sintetiza cada um e concatena com uma
        pausa breve entre eles — narração longa sem viajar nem travar."""
        chunks = _chunk_text(clean)
        if len(chunks) <= 1:
            return self._tts_once(chunks[0] if chunks else clean, speaker)
        gap = np.zeros(int(SAMPLE_RATE * 0.14), dtype=np.float32)  # ~140ms entre blocos
        pieces: list[np.ndarray] = []
        for i, ch in enumerate(chunks):
            if i:
                pieces.append(gap)
            pieces.append(self._tts_once(ch, speaker))
        return np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.float32)

    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE_ID,
        speed: float = 1.0,
        language: str = "pt",
    ) -> bytes:
        self.ensure_loaded()
        speaker = resolve_voice(voice_id).id  # id do catálogo = falante do XTTS
        clean = _sanitize_text(text)
        if sum(ch.isalpha() for ch in clean) < 2:
            return _silence_wav(0.18)
        with self._synth_lock:
            try:
                wav = self._generate(clean, speaker)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "device-side assert" in msg:
                    logger.error("device-side assert no XTTS; recarregando o modelo")
                    self._reload_locked()
                    wav = self._generate(clean, speaker)
                elif "cuda" in msg or "out of memory" in msg:
                    logger.warning("Erro CUDA no XTTS (%s) — limpando VRAM e repetindo", str(exc)[:90])
                    _empty_cache()
                    wav = self._generate(clean, speaker)
                else:
                    raise
        return _wav_bytes_from_array(_trim_audio(_to_mono_float(wav)))

    def empty_cache(self) -> None:
        _empty_cache()

    def _reload_locked(self) -> None:
        self._tts = None
        _empty_cache()


_xtts: XTTSEngine | None = None


def get_xtts_engine() -> XTTSEngine:
    global _xtts
    if _xtts is None:
        _xtts = XTTSEngine()
    return _xtts
