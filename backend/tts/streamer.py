from __future__ import annotations

import re
from pathlib import Path

from backend.config import CACHE_DIR
from backend.utils.paths import audio_cache_path

_FALLBACK_SENT_RE = re.compile(r"(?<=[\.\!\?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ])")
_CACHE_LIMIT_BYTES = 500 * 1024 * 1024


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    try:
        import nltk

        try:
            from nltk.tokenize import sent_tokenize

            return [s.strip() for s in sent_tokenize(text, language="portuguese") if s.strip()]
        except LookupError:
            try:
                nltk.download("punkt_tab", quiet=True)
                from nltk.tokenize import sent_tokenize

                return [
                    s.strip() for s in sent_tokenize(text, language="portuguese") if s.strip()
                ]
            except Exception:
                pass
    except Exception:
        pass

    parts = _FALLBACK_SENT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


_ENUM_ONLY_RE = re.compile(
    r"^\s*\(?\s*(?:\d{1,3}|[ivxlcdmIVXLCDM]{1,7}|\d{1,3}\s*[–—-]\s*\d{1,3})\s*\)?\s*[.)\]:–-]?\s*$"
)


def merge_enumerators(parts: list[str]) -> list[str]:
    """Junta marcadores de enumeração soltos ('4.', '(1)', '5–6.', 'II.') à frase
    seguinte. Esses fragmentos sem letras travam o TTS e atrapalham a leitura."""
    out: list[str] = []
    carry = ""
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if carry:
            p = f"{carry} {p}"
            carry = ""
        if _ENUM_ONLY_RE.match(p):
            carry = p
        else:
            out.append(p)
    if carry:
        out.append(carry)
    return out


def get_or_synthesize(text: str, voice_id: str, speed: float = 1.0) -> bytes:
    """Return cached WAV bytes or synthesize and cache.

    A chave de cache é normalizada: voz única (id canônico) e sempre 1.0x — a
    velocidade é aplicada no cliente (playbackRate). Assim a pré-geração em
    background e o playback compartilham exatamente o mesmo cache."""
    from backend.tts.voices import resolve_voice

    canonical = resolve_voice(voice_id).id
    path = audio_cache_path(text, canonical, 1.0)
    if path.exists():
        return path.read_bytes()
    from backend.tts.engine import get_engine

    wav = get_engine().synthesize(text, voice_id=canonical, speed=1.0)
    path.write_bytes(wav)
    _enforce_cache_limit()
    return wav


def _enforce_cache_limit() -> None:
    audio_dir = CACHE_DIR / "audio"
    if not audio_dir.exists():
        return
    files: list[tuple[Path, int, float]] = []
    total = 0
    for f in audio_dir.iterdir():
        if not f.is_file():
            continue
        st = f.stat()
        files.append((f, st.st_size, st.st_atime))
        total += st.st_size
    if total <= _CACHE_LIMIT_BYTES:
        return
    files.sort(key=lambda t: t[2])
    for f, size, _ in files:
        if total <= _CACHE_LIMIT_BYTES:
            break
        try:
            f.unlink()
            total -= size
        except OSError:
            continue
