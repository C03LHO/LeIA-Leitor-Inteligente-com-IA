from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field

import httpx

# Wikimedia (ws-export/MediaWiki) exige um User-Agent identificável, com URL de
# contato — sem isso devolve 403. Mantemos um UA compatível para todas as fontes.
USER_AGENT = (
    "LeIA/1.0 (leitor local de livros; "
    "+https://github.com/AurelioGabriel/LeIA-Leitor-Inteligente-com-IA) httpx"
)

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def client() -> httpx.Client:
    """Cliente HTTP com UA e follow-redirects (Gutenberg/ws-export redirecionam)."""
    return httpx.Client(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


@dataclass
class SourceHit:
    """Um livro encontrado numa fonte. `download_url` pode vir vazio e ser
    resolvido depois (Internet Archive resolve o arquivo só na importação)."""

    source: str                 # "gutenberg" | "wikisource" | "archive"
    id: str                     # identificador dentro da fonte
    title: str
    author: str = ""
    language: str = "pt"
    ext: str = ".epub"          # extensão esperada do download
    download_url: str = ""      # link direto (se conhecido na busca)
    detail_url: str = ""        # página humana da obra
    cover_url: str = ""         # capa (se houver)
    warning: str = ""           # aviso a exibir (Internet Archive)
    subjects: list = field(default_factory=list)  # gêneros/assuntos
    downloads: int = 0          # popularidade (nº de downloads)
    summary: str = ""           # sinopse, quando a fonte fornece

    def to_dict(self) -> dict:
        return asdict(self)


# Nome amigável de cada fonte para a interface.
SOURCE_LABELS = {
    "gutenberg": "Project Gutenberg",
    "wikisource": "Wikisource",
    "archive": "Internet Archive",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")
# Sufixos comuns que atrapalham o agrupamento entre fontes.
_NOISE = re.compile(
    r"\b(the|a|an|o|a|os|as|um|uma|de|do|da|dos|das|e|complete|completo|"
    r"volume|vol|tomo|parte|part)\b"
)


def norm_title(title: str) -> str:
    """Chave normalizada do título — junta a mesma obra vinda de fontes diferentes."""
    base = strip_accents(title or "").lower()
    base = _NON_WORD.sub(" ", base)
    base = _NOISE.sub(" ", base)
    base = _SPACES.sub(" ", base).strip()
    return base


def norm_author(author: str) -> str:
    base = strip_accents(author or "").lower()
    base = _NON_WORD.sub(" ", base)
    return _SPACES.sub(" ", base).strip()


def authors_conflict(a: str, b: str) -> bool:
    """True quando dois autores são claramente pessoas diferentes (não apenas
    um vazio ou um contido no outro, ex.: 'Machado de Assis' vs 'Assis')."""
    na, nb = norm_author(a), norm_author(b)
    if not na or not nb:
        return False
    return not (na in nb or nb in na)
