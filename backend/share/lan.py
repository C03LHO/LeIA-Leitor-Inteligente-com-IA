"""Transferência para o celular pela rede local (Wi-Fi).

Sobe um servidor HTTP temporário em 0.0.0.0 (separado do app, que só escuta em
127.0.0.1), servindo o audiolivro num link protegido por token. O celular abre
o link (ou lê o QR) e baixa o arquivo. Os links expiram sozinhos.
"""
from __future__ import annotations

import base64
import io
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from backend.utils.logging import get_logger

logger = get_logger("share.lan")

_shares: dict[str, dict] = {}   # token -> {path, filename, title, expires}
_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None
_port: int | None = None


def lan_ip() -> str:
    """IP da máquina na rede local (o que o celular consegue acessar)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _purge_expired() -> None:
    now = time.time()
    with _lock:
        for tok in [t for t, s in _shares.items() if s["expires"] < now]:
            _shares.pop(tok, None)


def _get(token: str) -> dict | None:
    _purge_expired()
    with _lock:
        return _shares.get(token)


_LANDING = """<!doctype html><html lang=pt-BR><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{title} — LeIA</title>
<style>
 body{{font-family:-apple-system,system-ui,sans-serif;background:#0e0e10;color:#eee;
 margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}}
 .card{{max-width:420px;text-align:center}}
 .mark{{width:64px;height:64px;border-radius:18px;background:linear-gradient(145deg,#fbbf24,#f59e0b);
 color:#111;font-weight:800;font-size:30px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px}}
 h1{{font-size:20px;margin:0 0 6px}} p{{color:#aaa;font-size:14px;line-height:1.5}}
 a.btn{{display:inline-block;margin-top:20px;padding:14px 28px;background:#f59e0b;color:#111;
 font-weight:700;border-radius:12px;text-decoration:none;font-size:16px}}
 small{{display:block;margin-top:18px;color:#777}}
</style></head><body><div class=card>
 <div class=mark>L</div>
 <h1>{title}</h1>
 <p>Audiolivro gerado no LeIA, pronto para o seu iPhone.<br>Toque para baixar e abra nos Livros ou num app de áudio.</p>
 <a class=btn href="/d/{token}">⬇ Baixar audiolivro</a>
 <small>Transferência 100% local, pela sua rede Wi-Fi.</small>
</div></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia o log padrão
        pass

    def _not_found(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"nao encontrado / expirado")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] not in ("s", "d"):
            return self._not_found()
        kind, token = parts
        share = _get(token)
        if not share:
            return self._not_found()
        if kind == "s":
            html = _LANDING.format(title=share["title"], token=token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        # kind == "d": baixa o arquivo
        fp = Path(share["path"])
        if not fp.exists():
            return self._not_found()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header(
            "Content-Disposition", f"attachment; filename*=UTF-8''{quote(share['filename'])}"
        )
        self.send_header("Content-Length", str(fp.stat().st_size))
        self.end_headers()
        with fp.open("rb") as f:
            while True:
                chunk = f.read(262144)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break


def _ensure_server() -> int:
    global _server, _port
    if _server is not None:
        return _port  # type: ignore[return-value]
    for port in range(8770, 8800):
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
        except OSError:
            continue
        _server = srv
        _port = port
        threading.Thread(target=srv.serve_forever, daemon=True, name="leia-share").start()
        logger.info("Servidor de compartilhamento em 0.0.0.0:%d", port)
        return port
    raise RuntimeError("Nenhuma porta livre para o compartilhamento (8770-8799).")


def _qr_b64(url: str) -> str:
    try:
        import qrcode

        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        logger.exception("Falha ao gerar QR")
        return ""


def start_share(file_path: str | Path, title: str, filename: str, ttl: int = 3600) -> dict:
    """Publica o arquivo na rede local e devolve {url, landing, qr, expires_in}."""
    fp = Path(file_path)
    if not fp.exists():
        raise RuntimeError("Arquivo do audiolivro não encontrado.")
    port = _ensure_server()
    token = secrets.token_urlsafe(10)
    with _lock:
        _shares[token] = {
            "path": str(fp),
            "filename": filename,
            "title": title,
            "expires": time.time() + ttl,
        }
    ip = lan_ip()
    landing = f"http://{ip}:{port}/s/{token}"
    return {
        "url": landing,
        "download": f"http://{ip}:{port}/d/{token}",
        "qr": _qr_b64(landing),
        "ip": ip,
        "port": port,
        "expires_in": ttl,
    }
