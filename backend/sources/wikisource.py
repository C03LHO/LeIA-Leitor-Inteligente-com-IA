from __future__ import annotations

from urllib.parse import quote

from backend.sources.base import SourceHit, client
from backend.utils.logging import get_logger

logger = get_logger("sources.wikisource")

API = "https://pt.wikisource.org/w/api.php"
# ws-export converte uma página da Wikisource em EPUB pronto.
WS_EXPORT = "https://ws-export.wmcloud.org/"


def _export_url(title: str) -> str:
    return f"{WS_EXPORT}?lang=pt&format=epub&page={quote(title.replace(' ', '_'))}"


def search(query: str, limit: int = 20) -> list[SourceHit]:
    """Busca obras na Wikisource em português (namespace principal)."""
    hits: list[SourceHit] = []
    try:
        with client() as c:
            r = c.get(
                API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srnamespace": "0",
                    "srlimit": str(limit),
                    "format": "json",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        logger.exception("Wikisource indisponível para '%s'", query)
        return hits

    for item in data.get("query", {}).get("search", []):
        title = (item.get("title") or "").strip()
        # Subpáginas ("Obra/Capítulo 1") são pedaços — queremos a obra inteira.
        if not title or "/" in title:
            continue
        hits.append(
            SourceHit(
                source="wikisource",
                id=title,
                title=title,
                author="",
                language="pt",
                ext=".epub",
                download_url=_export_url(title),
                detail_url=f"https://pt.wikisource.org/wiki/{quote(title.replace(' ', '_'))}",
            )
        )
    return hits


def resolve(hit: dict) -> tuple[str, str]:
    title = hit.get("id") or hit.get("title", "")
    return _export_url(title), ".epub"
