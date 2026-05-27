from __future__ import annotations

import io
import threading
import wave
from dataclasses import dataclass

import numpy as np

from backend.tts.voices import DEFAULT_VOICE_ID, Voice, resolve_voice
from backend.utils.logging import get_logger

logger = get_logger("tts.engine")

XTTS_MODEL_ID = "tts_models/multilingual/multi-dataset/xtts_v2"
SAMPLE_RATE = 24000


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
    """Lazy wrapper around Coqui XTTS-v2 with embedded + custom voice support."""

    def __init__(self) -> None:
        self.hardware = detect_hardware()
        self._tts = None
        self._lock = threading.Lock()
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
                from TTS.api import TTS  # heavy import

                logger.info(
                    "Carregando XTTS-v2 (device=%s, gpu=%s)",
                    self.hardware.device,
                    self.hardware.gpu_name,
                )
                gpu = self.hardware.cuda_available
                self._tts = TTS(XTTS_MODEL_ID, gpu=gpu)
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Falha ao carregar XTTS-v2")
                raise

    def synthesize(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE_ID,
        speed: float = 1.0,
        language: str = "pt",
    ) -> bytes:
        assert language == "pt", "Apenas pt-BR é suportado nesta versão"
        self.ensure_loaded()
        voice = resolve_voice(voice_id)
        wav = self._invoke_tts(text, voice, speed, language)
        return _wav_bytes_from_array(wav)

    def synthesize_to_array(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE_ID,
        speed: float = 1.0,
        language: str = "pt",
    ):
        self.ensure_loaded()
        voice = resolve_voice(voice_id)
        return self._invoke_tts(text, voice, speed, language)

    def _invoke_tts(self, text: str, voice: Voice, speed: float, language: str):
        kwargs: dict = {"text": text, "language": language, "speed": speed}
        if voice.kind == "embedded" and voice.speaker:
            kwargs["speaker"] = voice.speaker
        elif voice.kind == "custom" and voice.wav_path:
            kwargs["speaker_wav"] = voice.wav_path
        else:
            raise ValueError(f"Voz {voice.id} sem speaker nem speaker_wav")
        return self._tts.tts(**kwargs)


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
