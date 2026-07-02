from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "LeIA"
APP_VERSION = "1.2.2"

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_RANGE = range(8765, 8776)

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"

_appdata = os.environ.get("APPDATA")
USER_DATA_DIR = Path(_appdata) / APP_NAME if _appdata else ROOT_DIR / ".leia"
MODELS_DIR = USER_DATA_DIR / "models"
CACHE_DIR = USER_DATA_DIR / "cache"
LOGS_DIR = USER_DATA_DIR / "logs"

for _d in (USER_DATA_DIR, MODELS_DIR, CACHE_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
