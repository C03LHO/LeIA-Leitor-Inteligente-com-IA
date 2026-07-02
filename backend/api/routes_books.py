from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

_DL_RETRIES = 3

from backend.api import routes_pdf
from backend.sources import SOURCES, gutendex, group_hits, search_all
from backend.sources.base import SOURCE_LABELS, USER_AGENT
from backend.utils.logging import get_logger
from backend.utils.paths import book_upload_path

logger = get_logger("api.books")
router = APIRouter(prefix="/api/books", tags=["books"])

_ALL_SOURCES = list(SOURCES.keys())
# Conexão generosa: mirrors do Gutenberg/ws-export às vezes demoram a responder.
_DL_TIMEOUT = httpx.Timeout(180.0, connect=30.0)


@router.get("/sources")
def list_sources():
    """Fontes disponíveis para a interface montar os filtros."""
    return {
        "sources": [
            {"id": s, "label": SOURCE_LABELS.get(s, s)} for s in _ALL_SOURCES
        ]
    }


# Gêneros da vitrine → termo de assunto do Gutenberg (subjects em inglês).
GENRES = [
    {"id": "romance", "label": "Romance", "topic": "love stories"},
    {"id": "aventura", "label": "Aventura", "topic": "adventure"},
    {"id": "ficcao", "label": "Ficção", "topic": "fiction"},
    {"id": "scifi", "label": "Ficção científica", "topic": "science fiction"},
    {"id": "terror", "label": "Terror", "topic": "horror"},
    {"id": "misterio", "label": "Mistério", "topic": "detective"},
    {"id": "poesia", "label": "Poesia", "topic": "poetry"},
    {"id": "contos", "label": "Contos", "topic": "short stories"},
    {"id": "teatro", "label": "Teatro", "topic": "drama"},
    {"id": "historia", "label": "História", "topic": "history"},
    {"id": "filosofia", "label": "Filosofia", "topic": "philosophy"},
    {"id": "infantil", "label": "Infantil", "topic": "children"},
]
_GENRE_TOPIC = {g["id"]: g["topic"] for g in GENRES}


@router.get("/genres")
def list_genres():
    return {"genres": [{"id": g["id"], "label": g["label"]} for g in GENRES]}


@router.get("/browse")
def browse_books(genre: str = "", page: int = 1):
    """Vitrine estilo Kindle: livros grátis em português por popularidade,
    opcionalmente por gênero. Só Project Gutenberg (tem capa, assunto e
    contagem de downloads)."""
    topic = _GENRE_TOPIC.get(genre, "") if genre else ""
    hits, has_more = gutendex.browse(topic=topic, page=max(1, page))
    return {"groups": group_hits(hits), "has_more": has_more, "page": max(1, page)}


@router.get("/search")
def search_books(q: str = "", sources: str = ""):
    """Busca livros em português nas fontes escolhidas e agrupa a mesma obra."""
    query = (q or "").strip()
    if len(query) < 2:
        return {"groups": []}
    wanted = [s.strip() for s in sources.split(",") if s.strip()] if sources else _ALL_SOURCES
    hits = search_all(query, wanted, limit=20)
    return {"groups": group_hits(hits)}


class ImportBody(BaseModel):
    source: str
    id: str
    title: str = ""
    author: str = ""
    download_url: str = ""
    ext: str = ""
    warning: str = ""
    prepare: bool = False


def _download_once(url: str, target: Path) -> int:
    total = 0
    with httpx.Client(
        timeout=_DL_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as c:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with target.open("wb") as fh:
                for chunk in r.iter_bytes(chunk_size=65536):
                    fh.write(chunk)
                    total += len(chunk)
    return total


def _download(url: str, target: Path) -> int:
    """Baixa (streaming) para `target`, com algumas tentativas — os mirrors
    de domínio público (Gutenberg, ws-export) são intermitentes."""
    last: Exception | None = None
    for attempt in range(1, _DL_RETRIES + 1):
        try:
            return _download_once(url, target)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            logger.warning("Download tentativa %d/%d falhou (%s): %s",
                           attempt, _DL_RETRIES, type(exc).__name__, url)
            target.unlink(missing_ok=True)
            if attempt < _DL_RETRIES:
                time.sleep(1.5 * attempt)
    raise last if last else RuntimeError("Download falhou")


def _ingest(job_id: str, body: ImportBody) -> None:
    filename = f"{(body.title or body.id).strip() or 'livro'}"
    try:
        # 1) Resolve o link de download (Internet Archive só sabe na hora).
        url, ext = body.download_url, (body.ext or "")
        if not url:
            module = SOURCES.get(body.source)
            if module is None:
                raise ValueError(f"Fonte desconhecida: {body.source}")
            url, ext = module.resolve(body.model_dump())
        if not url or ext not in routes_pdf.SUPPORTED_EXTS:
            raise ValueError("Sem arquivo compatível (.epub/.pdf) nesta fonte")

        routes_pdf._jobs[job_id] = {
            "status": "processing", "progress": 0.15, "filename": filename
        }

        # 2) Baixa o arquivo para o mesmo lugar dos uploads.
        target = book_upload_path(job_id, ext)
        size = _download(url, target)
        if size <= 0:
            raise ValueError("Download vazio")
        logger.info("Baixado %s (%s, %d bytes) de %s", filename, ext, size, body.source)

        # 3) Reaproveita todo o pipeline de extração/limpeza/estrutura.
        routes_pdf._process_book(
            job_id, target, f"{filename}{ext}", ext, None, body.prepare
        )

        # 4) Preserva os metadados bonitos da fonte + marca a origem/aviso.
        fields = {"source": body.source}
        if body.title:
            fields["title"] = body.title
        if body.author:
            fields["author"] = body.author
        if body.warning:
            fields["source_warning"] = body.warning
        routes_pdf._library_put(job_id, **fields)
    except Exception as exc:
        logger.exception("Importação falhou (job %s)", job_id)
        routes_pdf._jobs[job_id] = {
            "status": "error", "progress": 1.0, "filename": filename, "error": str(exc)
        }


@router.post("/import")
def import_book(body: ImportBody, background: BackgroundTasks):
    if body.source not in SOURCES:
        raise HTTPException(status_code=400, detail="Fonte inválida")
    job_id = uuid.uuid4().hex[:12]
    routes_pdf._jobs[job_id] = {
        "status": "queued", "progress": 0.0, "filename": body.title or body.id,
        "created_at": time.time(),
    }
    background.add_task(_ingest, job_id, body)
    return {"job_id": job_id, "title": body.title, "source": body.source}
