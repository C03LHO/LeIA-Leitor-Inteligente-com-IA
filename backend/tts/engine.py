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

# Parâmetros de geração afinados para narração estável (menos suspiros/ruídos
# alucinados que os defaults 0.8/0.5): temperatura e expressividade mais baixas.
GEN_KWARGS = {
    "temperature": 0.7,
    "exaggeration": 0.4,
    "cfg_weight": 0.5,
    "repetition_penalty": 2.0,
}


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
                wav = self._tts.generate(clean, language_id=LANGUAGE_ID, **GEN_KWARGS)
            except RuntimeError as exc:
                if "CUDA" in str(exc):
                    logger.error("Erro CUDA na síntese; recarregando o modelo e tentando de novo")
                    self._reload_locked()
                    wav = self._tts.generate(clean, language_id=LANGUAGE_ID, **GEN_KWARGS)
                else:
                    raise
        return _wav_bytes_from_array(_trim_audio(_to_mono_float(wav)))

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


def _trim_audio(arr: np.ndarray) -> np.ndarray:
    """Apara silêncio/artefatos das pontas (energia por janelas de 20ms) e aplica
    fades curtos. Remove o dead-air entre frases e suaviza respiros no fim."""
    arr = np.asarray(arr, dtype=np.float32)
    sr = SAMPLE_RATE
    if arr.size < int(sr * 0.12):
        return arr
    win = max(1, int(sr * 0.02))
    n = arr.size // win
    if n < 3:
        return arr
    frames = arr[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-9)
    peak = float(rms.max())
    if peak <= 1e-4:
        return arr
    thr = max(peak * 0.08, 0.006)
    voiced = np.where(rms > thr)[0]
    if voiced.size == 0:
        return arr
    start = max(0, int(voiced[0] * win - sr * 0.03))     # 30ms antes da fala
    end = min(arr.size, int((voiced[-1] + 1) * win + sr * 0.06))  # 60ms depois
    out = arr[start:end].copy()
    f = min(int(sr * 0.006), out.size // 2)               # fade de ~6ms nas pontas
    if f > 0:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        out[:f] *= ramp
        out[-f:] *= ramp[::-1]
    return out


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
