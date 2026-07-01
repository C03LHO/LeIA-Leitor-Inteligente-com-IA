"""Fontes de livros gratuitos (Project Gutenberg, Wikisource pt, Internet Archive).

Cada adaptador expõe `search(query, limit)` retornando uma lista de `SourceHit`
e, quando o link de download não é conhecido na busca, `resolve(hit)` para
descobri-lo na hora da importação. Tudo restrito a português.
"""

from backend.sources.base import SourceHit
from backend.sources.aggregate import SOURCES, group_hits, search_all

__all__ = ["SourceHit", "SOURCES", "group_hits", "search_all"]
