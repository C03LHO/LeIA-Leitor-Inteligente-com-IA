from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "LeIA"
APP_VERSION = "1.5.2"

# Motor de narração: "xtts" (XTTS-v2, ~2GB VRAM, mais estável em placa lotada) ou
# "chatterbox" (voz nativa pt-BR, ~5.6GB VRAM). Trocável por variável de ambiente.
TTS_ENGINE = os.environ.get("LEIA_TTS_ENGINE", "xtts").strip().lower()
# Falante embutido do XTTS-v2 para pt-BR (não precisa de áudio de referência).
XTTS_SPEAKER = os.environ.get("LEIA_XTTS_SPEAKER", "Ana Florence")

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
