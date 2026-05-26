from __future__ import annotations

from fastapi import APIRouter

from backend.config import APP_NAME, APP_VERSION
from backend.tts.engine import detect_hardware, get_engine

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def system_status():
    hw = detect_hardware()
    engine = get_engine()
    return {
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "hardware": hw.to_dict(),
        "tts": {
            "loaded": engine.loaded,
            "load_error": engine.load_error,
        },
    }


@router.post("/warmup")
def warmup():
    """Force XTTS-v2 to load now (downloads weights on first call)."""
    engine = get_engine()
    try:
        engine.ensure_loaded()
        return {"ok": True, "loaded": engine.loaded}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
