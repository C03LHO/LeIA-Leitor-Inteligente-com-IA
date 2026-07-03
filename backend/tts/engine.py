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
# temperatura menor = menos "viagem" (o modelo inventa menos fala fora do texto).
GEN_KWARGS = {
    "temperature": 0.6,
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


def _tune_perf() -> None:
    """Liga otimizações da GPU (TF32 + autotuner) para máxima velocidade."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
    except Exception:
        pass


def _empty_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


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
                _tune_perf()  # TF32 + cudnn.benchmark → GPU no máximo
                self._tts = ChatterboxMultilingualTTS.from_pretrained(device=device)
            except Exception as exc:
                self._load_error = str(exc)
                logger.exception("Falha ao carregar Chatterbox")
                raise

    def _generate(self, clean: str):
        import torch

        # inference_mode = mais rápido e usa menos VRAM que o modo normal.
        with torch.inference_mode():
            return self._tts.generate(clean, language_id=LANGUAGE_ID, **GEN_KWARGS)

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
                wav = self._generate(clean)
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "device-side assert" in msg:
                    # Contexto CUDA envenenado → aqui SIM precisa recarregar.
                    logger.error("device-side assert na síntese; recarregando o modelo")
                    self._reload_locked()
                    wav = self._generate(clean)
                elif "cuda" in msg or "out of memory" in msg:
                    # OOM/erro transitório: limpa o cache e tenta DE NOVO SEM reload.
                    # (recarregar a cada erro causava thrashing e travava o preparo.)
                    logger.warning("Erro CUDA na síntese (%s) — limpando VRAM e repetindo", str(exc)[:90])
                    _empty_cache()
                    wav = self._generate(clean)
                else:
                    raise
        return _wav_bytes_from_array(_trim_audio(_to_mono_float(wav)))

    def empty_cache(self) -> None:
        _empty_cache()

    def _reload_locked(self) -> None:
        """Best-effort: recarrega o modelo após um erro CUDA GRAVE (device-side
        assert). Chamado sob _synth_lock."""
        self._tts = None
        _empty_cache()
        self.ensure_loaded()


# Pontuação que o modelo lê/pausa bem. Todo o resto que não for letra latina,
# dígito ou espaço vira espaço (evita que o modelo "leia" símbolos ou alucine).
_ALLOWED_PUNCT = set(".,;:!?()\"'")

# Substituições explícitas: normaliza aspas/traços/reticências e troca alguns
# símbolos por palavras faladas ou por uma pausa.
_CHAR_MAP = {
    "–": ",", "—": ",", "―": ",", "−": "-",          # travessões → pausa curta
    "…": ".", "•": " ", "·": " ", "‣": " ", "◦": " ", "▪": " ", "●": " ",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‟": '"',
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "`": "'", "´": "'",
    " ": " ", " ": " ", " ": " ",       # espaços especiais
    "​": "", "‌": "", "‍": "", "﻿": "",  # zero-width
    "&": " e ", "@": " arroba ", "%": " por cento ", "°": " graus ",
    "/": " ", "\\": " ", "*": " ", "_": " ", "|": " ", "~": " ",
    "^": " ", "=": " ", "+": " ", "<": " ", ">": " ", "#": " ", "$": " ",
    "[": "(", "]": ")", "{": "(", "}": ")",
}


def _is_speakable_char(ch: str) -> bool:
    """True para o que o modelo pt-BR lê bem: letra latina, dígito, espaço ou
    pontuação básica. Descarta emojis, formas geométricas, setas, símbolos
    matemáticos e escritas não-latinas (cirílico, grego, CJK…)."""
    if ch in (" ", "\t", "\n") or ch in _ALLOWED_PUNCT:
        return True
    if "0" <= ch <= "9":
        return True
    # Letra dentro do alcance latino (ASCII + Latin-1/Extended-A/B → cobre pt-BR).
    if ch.isalpha() and ord(ch) <= 0x24F:
        return True
    return False


def _sanitize_text(text: str) -> str:
    """Deixa só texto realmente falável em português. Símbolos, formas
    geométricas e escritas estrangeiras viram espaço — o que impede o modelo
    de "ler" essas coisas ou viajar inventando fala fora do texto."""
    t = unicodedata.normalize("NFC", text or "")
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)   # URLs leem horrível
    t = re.sub(r"\S+@\S+\.\w+", " ", t)             # e-mails
    t = "".join(_CHAR_MAP.get(ch, ch) for ch in t)
    t = "".join(ch if _is_speakable_char(ch) else " " for ch in t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,;:!?)])", r"\1", t)        # espaço antes de pontuação
    t = re.sub(r"([.,;:!?])\1+", r"\1", t)          # pontuação repetida → uma
    t = re.sub(r"\(\s*\)", " ", t)                   # parênteses vazios
    return re.sub(r"\s+", " ", t).strip()[:800]


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
