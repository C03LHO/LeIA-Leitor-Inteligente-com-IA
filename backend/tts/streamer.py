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


def get_or_synthesize(text: str, voice_id: str, speed: float) -> bytes:
    """Return cached WAV bytes for (text, voice_id, speed) or synthesize and cache."""
    path = audio_cache_path(text, voice_id, speed)
    if path.exists():
        return path.read_bytes()
    from backend.tts.engine import get_engine

    wav = get_engine().synthesize(text, voice_id=voice_id, speed=speed)
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
