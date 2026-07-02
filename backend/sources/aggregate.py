from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backend.sources import archive, gutendex, wikisource
from backend.sources.base import SOURCE_LABELS, SourceHit, authors_conflict, norm_title

# Registro das fontes: nome → módulo (com search/resolve).
SOURCES = {
    "gutenberg": gutendex,
    "wikisource": wikisource,
    "archive": archive,
}


def search_all(query: str, sources: list[str], limit: int = 20) -> list[SourceHit]:
    """Consulta as fontes pedidas em paralelo; uma falha não derruba as outras."""
    active = [s for s in sources if s in SOURCES]
    if not active:
        return []

    results: list[SourceHit] = []
    with ThreadPoolExecutor(max_workers=len(active)) as pool:
        futures = {pool.submit(SOURCES[s].search, query, limit): s for s in active}
        for fut in futures:
            try:
                results.extend(fut.result() or [])
            except Exception:
                pass
    return results


def group_hits(hits: list[SourceHit]) -> list[dict]:
    """Agrupa a mesma obra vinda de fontes diferentes, para o usuário escolher
    de onde baixar. Agrupa por título; só separa quando os autores são
    claramente pessoas diferentes (evita fundir 'Poesias' de autores distintos,
    mas junta uma obra mesmo quando uma das fontes não informa o autor)."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for h in hits:
        tkey = norm_title(h.title)
        if not tkey:
            continue
        # Procura um grupo com o mesmo título e autor compatível.
        key = tkey
        suffix = 1
        while key in groups and authors_conflict(groups[key]["author"], h.author):
            suffix += 1
            key = f"{tkey}#{suffix}"
        if key not in groups:
            groups[key] = {
                "key": key,
                "title": h.title,
                "author": h.author,
                "cover_url": h.cover_url,
                "warning": h.warning,
                "subjects": list(h.subjects or []),
                "downloads": int(h.downloads or 0),
                "summary": h.summary or "",
                "sources": [],
            }
            order.append(key)
        g = groups[key]
        if h.subjects and not g["subjects"]:
            g["subjects"] = list(h.subjects)
        if h.downloads and h.downloads > g["downloads"]:
            g["downloads"] = int(h.downloads)
        if h.summary and len(h.summary) > len(g["summary"]):
            g["summary"] = h.summary
        # Prefere um título/autor mais informativo e uma capa quando surgir.
        if len(h.title) > len(g["title"]):
            g["title"] = h.title
        if h.author and not g["author"]:
            g["author"] = h.author
        if h.cover_url and not g["cover_url"]:
            g["cover_url"] = h.cover_url
        if h.warning:
            g["warning"] = h.warning
        g["sources"].append(
            {
                "source": h.source,
                "label": SOURCE_LABELS.get(h.source, h.source),
                "id": h.id,
                "ext": h.ext,
                "download_url": h.download_url,
                "detail_url": h.detail_url,
                "warning": h.warning,
            }
        )
    return [groups[k] for k in order]
