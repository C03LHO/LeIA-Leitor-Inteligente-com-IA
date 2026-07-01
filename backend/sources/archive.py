from __future__ import annotations

from urllib.parse import quote

from backend.sources.base import SourceHit, client
from backend.utils.logging import get_logger

logger = get_logger("sources.archive")

SEARCH_API = "https://archive.org/advancedsearch.php"
META_API = "https://archive.org/metadata/"
DOWNLOAD = "https://archive.org/download/"

WARNING = (
    "Do Internet Archive — o status de domínio público varia por país. "
    "Confirme se você pode baixar/ouvir esta obra na sua região."
)

# Formato → extensão que o pipeline entende, por ordem de preferência.
_PREFERRED_EXT = (".epub", ".pdf")


def search(query: str, limit: int = 20) -> list[SourceHit]:
    """Busca textos em português no Internet Archive (com aviso obrigatório)."""
    hits: list[SourceHit] = []
    params = [
        ("q", f"{query} AND language:(portuguese) AND mediatype:texts"),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "creator"),
        ("fl[]", "language"),
        ("rows", str(limit)),
        ("page", "1"),
        ("output", "json"),
    ]
    try:
        with client() as c:
            r = c.get(SEARCH_API, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Internet Archive indisponível para '%s'", query)
        return hits

    for doc in data.get("response", {}).get("docs", []):
        ident = doc.get("identifier")
        if not ident:
            continue
        creator = doc.get("creator", "")
        if isinstance(creator, list):
            creator = ", ".join(str(x) for x in creator)
        title = doc.get("title", "")
        if isinstance(title, list):
            title = title[0] if title else ""
        hits.append(
            SourceHit(
                source="archive",
                id=ident,
                title=(title or "").strip(),
                author=str(creator).strip(),
                language="pt",
                ext="",  # resolvido na importação
                download_url="",
                detail_url=f"https://archive.org/details/{quote(ident)}",
                cover_url=f"https://archive.org/services/img/{quote(ident)}",
                warning=WARNING,
            )
        )
    return hits


def resolve(hit: dict) -> tuple[str, str]:
    """Descobre um arquivo EPUB/PDF do item no momento da importação."""
    ident = hit.get("id", "")
    if not ident:
        return "", ""
    try:
        with client() as c:
            r = c.get(f"{META_API}{quote(ident)}")
            r.raise_for_status()
            files = r.json().get("files", [])
    except Exception:
        logger.exception("Falha ao resolver arquivo do IA '%s'", ident)
        return "", ""

    names = [f.get("name", "") for f in files if f.get("name")]
    for ext in _PREFERRED_EXT:
        for name in names:
            if name.lower().endswith(ext):
                return f"{DOWNLOAD}{quote(ident)}/{quote(name)}", ext
    return "", ""
