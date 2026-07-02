from __future__ import annotations

from backend.sources.base import SourceHit, client
from backend.utils.logging import get_logger

logger = get_logger("sources.gutendex")

API = "https://gutendex.com/books"

# Ordem de preferência de formato → extensão que o nosso pipeline entende.
_PREFERRED = (
    ("application/epub+zip", ".epub"),
    ("application/pdf", ".pdf"),
)


def _pick_format(formats: dict) -> tuple[str, str]:
    for mime, ext in _PREFERRED:
        for key, url in formats.items():
            # ".zip" costuma ser pacote de imagens, não o livro; ignore.
            if key.startswith(mime) and isinstance(url, str) and not url.endswith(".zip"):
                return url, ext
    return "", ""


def _cover(formats: dict) -> str:
    for key, url in formats.items():
        if key.startswith("image/") and isinstance(url, str):
            return url
    return ""


def _hit_from_book(b: dict) -> SourceHit | None:
    formats = b.get("formats", {}) or {}
    url, ext = _pick_format(formats)
    if not url:
        return None
    authors = ", ".join(a.get("name", "") for a in b.get("authors", []) if a.get("name"))
    gid = str(b.get("id"))
    summaries = b.get("summaries") or []
    return SourceHit(
        source="gutenberg",
        id=gid,
        title=(b.get("title") or "").strip(),
        author=authors,
        language="pt",
        ext=ext,
        download_url=url,
        detail_url=f"https://www.gutenberg.org/ebooks/{gid}",
        cover_url=_cover(formats),
        subjects=[s for s in (b.get("subjects") or []) if s][:6],
        downloads=int(b.get("download_count") or 0),
        summary=(summaries[0].strip() if summaries else ""),
    )


def _query(params: dict, limit: int) -> tuple[list[SourceHit], bool]:
    """Executa uma consulta ao Gutendex e devolve (hits, tem_mais_páginas)."""
    hits: list[SourceHit] = []
    try:
        with client() as c:
            r = c.get(API, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Gutendex indisponível (%s)", params)
        return hits, False
    for b in data.get("results", [])[:limit]:
        h = _hit_from_book(b)
        if h:
            hits.append(h)
    return hits, bool(data.get("next"))


def search(query: str, limit: int = 20) -> list[SourceHit]:
    """Busca no Project Gutenberg (via Gutendex), só livros em português."""
    hits, _ = _query({"search": query, "languages": "pt"}, limit)
    return hits


def browse(topic: str = "", page: int = 1, limit: int = 24) -> tuple[list[SourceHit], bool]:
    """Navegação estilo vitrine: livros em pt ordenados por popularidade
    (nº de downloads), opcionalmente filtrados por gênero/assunto (`topic`).
    Devolve (hits, tem_mais)."""
    params: dict = {"languages": "pt", "sort": "popular", "page": max(1, page)}
    if topic:
        params["topic"] = topic
    return _query(params, limit)


def resolve(hit: dict) -> tuple[str, str]:
    """Gutenberg já traz o link direto na busca."""
    return hit.get("download_url", ""), hit.get("ext", ".epub")
