from __future__ import annotations

import io
import re
import threading
import unicodedata
import wave
from dataclasses import dataclass

import numpy as np

from backend.tts.voices import DEFAULT_VOICE_ID, resolve_voice
from backend.utils.logging import get_logger

logger = get_logger("tts.engine")

# Chatterbox Multilingual gera áudio em 24 kHz mono.
SAMPLE_RATE = 24000
LANGUAGE_ID = "pt"


@dataclass
class HardwareInfo:
    device: str
    gpu_name: str | None
    vram_mb: int | None
    cuda_available: bool

    def to_dict(self) -> dict:
        return {
            "device": self.device,
            "gpu_name": self.gpu_name,
            "vram_mb": self.vram_mb,
            "cuda_available": self.cuda_available,
        }


def detect_hardware() -> HardwareInfo:
    try:
        import torch
    except Exception:
        return HardwareInfo(device="cpu", gpu_name=None, vram_mb=None, cuda_available=False)
    if torch.cuda.is_available():
        idx = torch.cuda.current_device()
        name = torch.cuda.get_device_name(idx)
        props = torch.cuda.get_device_properties(idx)
        return HardwareInfo(
            device="cuda",
            gpu_name=name,
            vram_mb=int(props.total_memory / (1024 * 1024)),
            cuda_available=True,
        )
    return HardwareInfo(device="cpu", gpu_name=None, vram_mb=None, cuda_available=False)


class TTSEngine:
    """Lazy wrapper around Chatterbox Multilingual TTS (single native pt-BR voice)."""

    def __init__(self) -> None:
        self.hardware = detect_hardware()
        self._tts = None
        self._lock = threading.Lock()
        self._synth_lock = threading.Lock()  # serializa o uso da GPU (pré-geração + playback)
        self._load_error: str | None = None

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
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # heavy import

                device = "cuda" if self.hardware.cuda_available else "cpu"
                logger.info("Carregando Chatterbox (device=%s, gpu=%s)", device, self.hardware.gpu_name)
                self._tts = ChatterboxMultilingualTTS.from_pretrained(device=device)
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Falha ao carregar Chatterbox")
                raise

    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE_ID,
        speed: float = 1.0,
        language: str = "pt",
    ) -> bytes:
        # `speed` é aplicado no cliente (playbackRate); a síntese é sempre em 1.0.
        self.ensure_loaded()
        resolve_voice(voice_id)  # valida/normaliza (voz única)
        clean = _sanitize_text(text)
        # Texto sem conteúdo falável (ex.: "4.", "(1)", "5–6.") faz o Chatterbox
        # disparar um device-side assert que ENVENENA o contexto CUDA (toda síntese
        # seguinte falha). Então nem chamamos o modelo: devolvemos um silêncio curto.
        if sum(ch.isalpha() for ch in clean) < 2:
            return _silence_wav(0.18)
        with self._synth_lock:
            try:
                wav = self._tts.generate(clean, language_id=LANGUAGE_ID)
            except RuntimeError as exc:
                if "CUDA" in str(exc):
                    logger.error("Erro CUDA na síntese; recarregando o modelo e tentando de novo")
                    self._reload_locked()
                    wav = self._tts.generate(clean, language_id=LANGUAGE_ID)
                else:
                    raise
        return _wav_bytes_from_array(_to_mono_float(wav))

    def _reload_locked(self) -> None:
        """Best-effort: recarrega o modelo após um erro CUDA (chamado sob _synth_lock)."""
        self._tts = None
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass
        self.ensure_loaded()


def _sanitize_text(text: str) -> str:
    """Normaliza unicode, remove caracteres de controle e limita o tamanho —
    reduz a chance de tokens fora do alcance que travam o modelo."""
    t = unicodedata.normalize("NFC", text or "")
    t = "".join(ch for ch in t if ch in (" ", "\t", "\n") or unicodedata.category(ch)[0] != "C")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:800]


def _silence_wav(seconds: float = 0.18) -> bytes:
    n = max(1, int(SAMPLE_RATE * seconds))
    return _wav_bytes_from_array(np.zeros(n, dtype=np.float32))


def _to_mono_float(wav) -> np.ndarray:
    """Aceita tensor torch [1, N] / [N] ou ndarray e devolve float32 1D."""
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().numpy()
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.reshape(-1) if 1 in arr.shape else arr.mean(axis=0)
    return arr


def _wav_bytes_from_array(samples) -> bytes:
    arr = np.asarray(samples, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    pcm = (arr * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 1)


_engine: TTSEngine | None = None


def get_engine() -> TTSEngine:
    global _engine
    if _engine is None:
        _engine = TTSEngine()
    return _engine
