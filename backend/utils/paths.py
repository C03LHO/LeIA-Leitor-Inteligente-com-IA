from __future__ import annotations

import hashlib
from pathlib import Path

from backend.config import CACHE_DIR


def audio_cache_path(text: str, voice: str, speed: float) -> Path:
    key = f"{voice}|{speed:.3f}|{text}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()
    audio_dir = CACHE_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir / f"{digest}.wav"


def pdf_upload_path(job_id: str) -> Path:
    pdf_dir = CACHE_DIR / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    return pdf_dir / f"{job_id}.pdf"


def pdf_result_path(job_id: str) -> Path:
    pdf_dir = CACHE_DIR / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    return pdf_dir / f"{job_id}.json"
