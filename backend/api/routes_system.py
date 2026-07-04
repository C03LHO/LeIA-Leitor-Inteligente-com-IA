from __future__ import annotations

import re
import time
import webbrowser

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import APP_NAME, APP_VERSION
from backend.tts.engine import detect_hardware, get_engine
from backend.utils.logging import get_logger

router = APIRouter(prefix="/api/system", tags=["system"])
logger = get_logger("api.system")

# A versão fica em backend/config.py e é bumpada a cada release. Comparamos com
# a versão no branch main do GitHub (não há releases/tags, então lemos o arquivo
# cru). Repositório do projeto:
_REPO = "C03LHO/LeIA-Leitor-Inteligente-com-IA"
_REPO_URL = f"https://github.com/{_REPO}"
_RAW_CONFIG = f"https://raw.githubusercontent.com/{_REPO}/main/backend/config.py"

_update_cache: dict | None = None
_update_ts = 0.0


def _ver_tuple(s: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def _check_for_update(force: bool = False) -> dict:
    global _update_cache, _update_ts
    now = time.monotonic()
    if _update_cache is not None and not force and now - _update_ts < 3600:
        return _update_cache
    latest = None
    try:
        import httpx

        resp = httpx.get(_RAW_CONFIG, timeout=5.0)
        m = re.search(r"APP_VERSION\s*=\s*[\"']([\d.]+)[\"']", resp.text)
        if m:
            latest = m.group(1)
    except Exception:
        logger.info("Checagem de atualização falhou (sem internet?)")
    result = {
        "current": APP_VERSION,
        "latest": latest,
        "update_available": bool(latest and _ver_tuple(latest) > _ver_tuple(APP_VERSION)),
        "url": _REPO_URL,
    }
    _update_cache, _update_ts = result, now
    return result


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


@router.get("/update-check")
def update_check(force: bool = False):
    return _check_for_update(force=force)


@router.post("/open-repo")
def open_repo():
    """Abre a página do projeto no navegador do sistema (o app roda em janela
    própria; window.open não abriria o navegador)."""
    try:
        webbrowser.open(_REPO_URL)
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/warmup")
def warmup():
    """Force XTTS-v2 to load now (downloads weights on first call)."""
    engine = get_engine()
    try:
        engine.ensure_loaded()
        return {"ok": True, "loaded": engine.loaded}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
