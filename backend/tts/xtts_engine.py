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
import threading

from backend.config import XTTS_SPEAKER
from backend.tts.engine import (
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

    def _generate(self, clean: str, speaker: str):
        import torch

        # repetition_penalty alto + top_k/top_p contêm o "rambling" (o XTTS às
        # vezes repete/estende demais). Também deixa a geração mais rápida.
        with torch.inference_mode():
            return self._tts.tts(
                text=clean,
                speaker=speaker,
                language="pt",
                split_sentences=True,
                temperature=0.7,
                repetition_penalty=5.0,
                length_penalty=1.0,
                top_k=50,
                top_p=0.85,
            )

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
