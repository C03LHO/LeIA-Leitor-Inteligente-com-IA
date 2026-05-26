from __future__ import annotations

import socket
import sys
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import routes_pdf, routes_system, routes_tts
from backend.config import APP_NAME, APP_VERSION, FRONTEND_DIR, HOST, PORT_RANGE
from backend.utils.logging import setup_logging

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.include_router(routes_system.router)
app.include_router(routes_pdf.router)
app.include_router(routes_tts.router)


@app.get("/api")
def api_root() -> dict[str, str]:
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


if FRONTEND_DIR.exists() and (FRONTEND_DIR / "index.html").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))

else:
    @app.get("/")
    def root_no_frontend() -> dict[str, str]:
        return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


def _pick_port() -> int:
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise RuntimeError(f"Nenhuma porta livre em {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


def main(open_browser: bool = False) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    setup_logging()
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    print(f"[{APP_NAME}] subindo em {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main(open_browser="--open" in sys.argv)
