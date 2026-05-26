from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.tts.voices import Voice, get_voice
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
    """Lazy wrapper around Coqui XTTS-v2.

    The actual model is loaded on first use to keep boot fast and to allow
    the rest of the app (PDF pipeline, frontend) to work even when the
    TTS stack isn't installed yet.
    """

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

    def synthesize_wav(
        self,
        text: str,
        voice: Voice | str = "default",
        speed: float = 1.0,
    ) -> bytes:
        """Synthesize the whole text and return a WAV byte string."""
        self.ensure_loaded()
        v = voice if isinstance(voice, Voice) else get_voice(voice)
        speaker_wav = str(v.sample_path) if v.sample_path.exists() else None
        wav = self._tts.tts(
            text=text,
            language=v.language,
            speaker_wav=speaker_wav,
            speed=speed,
        )
        return _wav_bytes_from_array(wav)

    def synthesize_sentence_stream(
        self,
        sentences: list[str],
        voice: Voice | str = "default",
        speed: float = 1.0,
    ):
        """Yield (index, sentence, wav_bytes) for each sentence."""
        self.ensure_loaded()
        v = voice if isinstance(voice, Voice) else get_voice(voice)
        speaker_wav = str(v.sample_path) if v.sample_path.exists() else None
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            wav = self._tts.tts(
                text=sentence,
                language=v.language,
                speaker_wav=speaker_wav,
                speed=speed,
            )
            yield i, sentence, _wav_bytes_from_array(wav)


def _wav_bytes_from_array(samples) -> bytes:
    import wave

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


_engine: TTSEngine | None = None


def get_engine() -> TTSEngine:
    global _engine
    if _engine is None:
        _engine = TTSEngine()
    return _engine
