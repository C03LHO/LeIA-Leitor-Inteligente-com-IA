from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import routes_books, routes_pdf, routes_system, routes_tts, routes_voices
from backend.config import APP_NAME, APP_VERSION, FRONTEND_DIR, HOST, PORT_RANGE
from backend.utils.logging import setup_logging

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.include_router(routes_system.router)
app.include_router(routes_pdf.router)
app.include_router(routes_books.router)
app.include_router(routes_tts.router)
app.include_router(routes_voices.router)


@app.get("/api")
def api_root() -> dict[str, str]:
    from backend.config import TTS_ENGINE

    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION, "engine": TTS_ENGINE}


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


def _serve_in_thread(port: int) -> uvicorn.Server:
    """Sobe o uvicorn numa thread daemon. Signal handlers só valem na main
    thread, então desligamos — quem controla o ciclo de vida é a janela."""
    config = uvicorn.Config(app, host=HOST, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    threading.Thread(target=server.run, daemon=True, name="leia-uvicorn").start()
    return server


def _wait_until_up(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _run_window(port: int) -> None:
    """Abre a interface numa JANELA NATIVA (WebView2). Se o pywebview/WebView2
    não estiver disponível, cai de volta para o navegador."""
    url = f"http://{HOST}:{port}"
    try:
        import webview
    except Exception:
        print("[LeIA] pywebview indisponível — abrindo no navegador.")
        _serve_in_thread(port)
        _wait_until_up(port)
        webbrowser.open(url)
        # mantém o processo vivo servindo (sem janela para bloquear)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    server = _serve_in_thread(port)
    if not _wait_until_up(port):
        print("[LeIA] o servidor não respondeu a tempo.")

    icon = FRONTEND_DIR / "favicon.ico"
    webview.create_window(
        f"{APP_NAME} — Leitor Inteligente com IA",
        url,
        width=1200,
        height=820,
        min_size=(940, 640),
    )
    # storage_path + private_mode=False → localStorage (progresso, marcadores,
    # estatísticas, ajustes) PERSISTE entre sessões e sobrevive a fechamento
    # brusco/queda de energia. Sem isso, o pywebview roda em modo privado e
    # apaga tudo ao fechar.
    from backend.config import USER_DATA_DIR
    storage = str(USER_DATA_DIR / "webview")
    try:
        webview.start(
            icon=str(icon) if icon.exists() else None,
            private_mode=False,
            storage_path=storage,
        )
    except TypeError:
        # backends/versões antigas: tenta ao menos persistir o storage
        try:
            webview.start(private_mode=False, storage_path=storage)
        except TypeError:
            webview.start()
    # Janela fechada → encerra o servidor e sai.
    server.should_exit = True


def main(open_browser: bool = False, window: bool = False) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    setup_logging()
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    print(f"[{APP_NAME}] subindo em {url}")
    if window:
        _run_window(port)
        return
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main(open_browser="--open" in sys.argv, window="--window" in sys.argv)
