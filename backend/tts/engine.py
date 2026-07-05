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

try:
    from backend.tts.normalize_ptbr import normalize as _normalize_ptbr
except Exception:  # num2words ausente → segue sem expandir números
    def _normalize_ptbr(t: str) -> str:
        return t

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


_HARDWARE: "HardwareInfo | None" = None
_CPU = HardwareInfo(device="cpu", gpu_name=None, vram_mb=None, cuda_available=False)


def detect_hardware() -> HardwareInfo:
    """Detecta a GPU UMA vez e cacheia. As chamadas CUDA (get_device_name/
    properties) podem BLOQUEAR se rodadas enquanto a GPU está sintetizando —
    por isso nunca reconsultamos: /api/system/status fica instantâneo."""
    global _HARDWARE
    if _HARDWARE is not None:
        return _HARDWARE
    try:
        import torch

        if torch.cuda.is_available():
            idx = torch.cuda.current_device()
            name = torch.cuda.get_device_name(idx)
            props = torch.cuda.get_device_properties(idx)
            _HARDWARE = HardwareInfo(
                device="cuda",
                gpu_name=name,
                vram_mb=int(props.total_memory / (1024 * 1024)),
                cuda_available=True,
            )
        else:
            _HARDWARE = _CPU
    except Exception:
        logger.exception("Falha ao detectar hardware; assumindo CPU")
        _HARDWARE = _CPU
    return _HARDWARE


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
        if not _is_speakable_text(text, clean):
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
    # Números/abreviações por extenso ANTES de descartar símbolos (ainda vê
    # R$, %, º): "R$ 45,90" -> "quarenta e cinco reais...", "séc. XIX" -> "...".
    t = _normalize_ptbr(t)
    t = "".join(_CHAR_MAP.get(ch, ch) for ch in t)
    t = "".join(ch if _is_speakable_char(ch) else " " for ch in t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,;:!?)])", r"\1", t)        # espaço antes de pontuação
    t = re.sub(r"([.,;:!?])\1+", r"\1", t)          # pontuação repetida → uma
    # Ponto/!/? COLADO à próxima palavra ("5.Assim", "fim.Outro") faz o XTTS
    # falar "ponto" em voz alta → garante um espaço para virar pausa natural.
    t = re.sub(r"([.!?])(?=[A-Za-zÀ-ÿ])", r"\1 ", t)
    t = re.sub(r"\(\s*\)", " ", t)                   # parênteses vazios
    return re.sub(r"\s+", " ", t).strip()[:800]


# Fragmento formado só por número + pontuação (nº de página, enumerador solto
# como "4.", "(1)", "5–6."). Nesses casos NÃO narramos — evita "quatro" solto no
# meio do livro. Exceção: quantidades marcadas (R$, %), que fazem sentido falar.
_BARE_MARKER_RE = re.compile(r"^[\s\d.,;:()\[\]\-–—…º°ª/*]+$")


def _is_speakable_text(raw: str, clean: str) -> bool:
    """False para texto degenerado (só símbolos/escrita estrangeira → vira vazio)
    ou fragmento só-número/marcador solto."""
    t = (raw or "").strip()
    if t and "%" not in t and "R$" not in t and _BARE_MARKER_RE.match(t):
        return False
    return sum(ch.isalpha() for ch in clean) >= 2


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


def _edge_fade(arr: np.ndarray, ms: float = 6.0) -> np.ndarray:
    """Fade curtíssimo nas pontas de um trecho. Aplicado a cada BLOCO antes de
    concatenar → elimina o clique/estalo nas junções (parte do 'ruído')."""
    arr = np.asarray(arr, dtype=np.float32)
    n = int(SAMPLE_RATE * ms / 1000.0)
    if n < 1 or arr.size < 2 * n:
        return arr
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    arr = arr.copy()
    arr[:n] *= ramp
    arr[-n:] *= ramp[::-1]
    return arr


def _polish_audio(arr: np.ndarray) -> np.ndarray:
    """Limpeza final: tira o offset DC e um filtro passa-alta suave (~55 Hz) que
    remove o rumble/zumbido de fundo do vocoder, deixando a voz mais limpa."""
    arr = np.asarray(arr, dtype=np.float32)
    if arr.size < 64:
        return arr
    arr = arr - float(np.mean(arr))  # remove DC
    try:
        from scipy.signal import butter, sosfilt

        sos = butter(2, 55.0 / (SAMPLE_RATE / 2.0), btype="highpass", output="sos")
        arr = sosfilt(sos, arr).astype(np.float32)
    except Exception:
        pass
    return arr


def _biquad_shelf(arr: np.ndarray, fc: float, gain_db: float, kind: str, q: float = 0.707) -> np.ndarray:
    """Filtro shelf (RBJ) — realça graves (calor) ou agudos (presença/ar) sem
    soar artificial. gain_db pequeno (+1 a +3) mantém a voz natural."""
    import math

    try:
        from scipy.signal import lfilter
    except Exception:
        return arr
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * fc / SAMPLE_RATE
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    sqA = math.sqrt(A)
    if kind == "high":
        b0 = A * ((A + 1) + (A - 1) * cw + 2 * sqA * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cw)
        b2 = A * ((A + 1) + (A - 1) * cw - 2 * sqA * alpha)
        a0 = (A + 1) - (A - 1) * cw + 2 * sqA * alpha
        a1 = 2 * ((A - 1) - (A + 1) * cw)
        a2 = (A + 1) - (A - 1) * cw - 2 * sqA * alpha
    else:  # low shelf
        b0 = A * ((A + 1) - (A - 1) * cw + 2 * sqA * alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cw)
        b2 = A * ((A + 1) - (A - 1) * cw - 2 * sqA * alpha)
        a0 = (A + 1) + (A - 1) * cw + 2 * sqA * alpha
        a1 = -2 * ((A - 1) + (A + 1) * cw)
        a2 = (A + 1) + (A - 1) * cw - 2 * sqA * alpha
    b = np.array([b0, b1, b2], dtype=np.float64) / a0
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return lfilter(b, a, arr).astype(np.float32)


def _reverb(arr: np.ndarray, wet: float = 0.04, decay: float = 0.26) -> np.ndarray:
    """Espaço/ambiência MUITO sutil — tira a secura sintética e dá 'vida' à voz,
    como se gravada numa sala pequena. wet baixo (~0.04) = quase imperceptível."""
    if wet <= 0:
        return arr
    try:
        from scipy.signal import fftconvolve

        n = int(SAMPLE_RATE * decay)
        if n < 8:
            return arr
        t = np.linspace(0.0, 1.0, n, dtype=np.float32)
        rng = np.random.RandomState(42)
        ir = rng.randn(n).astype(np.float32) * np.exp(-5.0 * t)
        k = max(1, int(SAMPLE_RATE * 0.002))
        ir = np.convolve(ir, np.ones(k, np.float32) / k, mode="same").astype(np.float32)
        ir[0] += 1.0  # som direto
        wetsig = fftconvolve(arr, ir)[: arr.size].astype(np.float32)
        m = float(np.max(np.abs(wetsig))) or 1.0
        wetsig *= (float(np.max(np.abs(arr))) or 0.0) / m
        return ((1.0 - wet) * arr + wet * wetsig).astype(np.float32)
    except Exception:
        return arr


def _gate(arr: np.ndarray, thresh: float = 0.045, floor_db: float = -13.0,
          win_ms: float = 12.0, smooth_ms: float = 30.0) -> np.ndarray:
    """Expander/gate suave: abaixa o sinal de BAIXO nível (o zumbido/'roco' que
    aparece na cauda das palavras, onde a voz cai) sem cortar a fala. O ganho é
    suavizado para não 'chiar' nem cortar abrupto."""
    if arr.size < 256:
        return arr
    w = max(1, int(SAMPLE_RATE * win_ms / 1000.0))
    env = np.sqrt(np.convolve(arr.astype(np.float64) ** 2, np.ones(w) / w, mode="same") + 1e-9)
    peak = float(env.max()) or 1.0
    t = thresh * peak
    floor = 10.0 ** (floor_db / 20.0)
    ratio = np.clip(env / t, 0.0, 1.0)            # 0 no silêncio, 1 na fala
    g = floor + (1.0 - floor) * ratio             # ramp suave floor->1
    sw = max(1, int(SAMPLE_RATE * smooth_ms / 1000.0))
    g = np.convolve(g, np.ones(sw) / sw, mode="same")
    return (arr * g.astype(np.float32)).astype(np.float32)


def _normalize_rms(arr: np.ndarray, target: float = 0.10, max_gain: float = 6.0, peak: float = 0.97) -> np.ndarray:
    """Loudness consistente entre frases (som 'produzido'), com teto de pico."""
    rms = float(np.sqrt(np.mean(arr * arr) + 1e-12))
    if rms < 1e-5:
        return arr
    arr = arr * min(target / rms, max_gain)
    pk = float(np.max(np.abs(arr))) if arr.size else 0.0
    if pk > peak:
        arr = arr * (peak / pk)
    return arr.astype(np.float32)


def _humanize_audio(arr: np.ndarray, wet: float = 0.0) -> np.ndarray:
    """Cadeia de 'humanização' da voz: calor leve, suaviza a aspereza digital,
    tira o zumbido das caudas ('roco no fim da palavra') e loudness consistente.
    EQ CONTIDA para não engrossar/abafar vozes graves (ex.: Damião)."""
    arr = np.asarray(arr, dtype=np.float32)
    if arr.size < 128:
        return arr
    # OBS.: NÃO usamos denoise espectral — a saída do XTTS já é limpa, e o
    # noisereduce criava "ruído musical" nos agudos (piorava).
    arr = _polish_audio(arr)                         # DC + passa-alta (rumble)
    arr = _biquad_shelf(arr, 220.0, 1.2, "low")      # calor leve (seguro p/ voz grave)
    arr = _biquad_shelf(arr, 8500.0, -1.8, "high")   # suaviza a aspereza "digital"
    arr = _gate(arr)                                 # tira o zumbido/roco nas caudas
    if wet > 0:
        arr = _reverb(arr, wet=wet)                  # ambiência opcional
    arr = _normalize_rms(arr, target=0.13)           # loudness consistente
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


def get_engine():
    """Devolve o motor de narração conforme config.TTS_ENGINE ('xtts' | 'chatterbox')."""
    from backend.config import TTS_ENGINE

    if TTS_ENGINE == "xtts":
        from backend.tts.xtts_engine import get_xtts_engine

        return get_xtts_engine()
    global _engine
    if _engine is None:
        _engine = TTSEngine()
    return _engine
