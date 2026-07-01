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


def search(query: str, limit: int = 20) -> list[SourceHit]:
    """Busca no Project Gutenberg (via Gutendex), só livros em português."""
    hits: list[SourceHit] = []
    try:
        with client() as c:
            r = c.get(API, params={"search": query, "languages": "pt"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Gutendex indisponível para '%s'", query)
        return hits

    for b in data.get("results", [])[:limit]:
        formats = b.get("formats", {}) or {}
        url, ext = _pick_format(formats)
        if not url:
            continue
        authors = ", ".join(a.get("name", "") for a in b.get("authors", []) if a.get("name"))
        gid = str(b.get("id"))
        hits.append(
            SourceHit(
                source="gutenberg",
                id=gid,
                title=(b.get("title") or "").strip(),
                author=authors,
                language="pt",
                ext=ext,
                download_url=url,
                detail_url=f"https://www.gutenberg.org/ebooks/{gid}",
                cover_url=_cover(formats),
            )
        )
    return hits


def resolve(hit: dict) -> tuple[str, str]:
    """Gutenberg já traz o link direto na busca."""
    return hit.get("download_url", ""), hit.get("ext", ".epub")
