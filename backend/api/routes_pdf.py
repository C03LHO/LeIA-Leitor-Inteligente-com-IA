from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.config import CACHE_DIR
from backend.epub.extractor import build_epub_document, extract_epub_cover
from backend.pdf.cleaner import CleaningConfig
from backend.pdf.extractor import blocks_as_jsonable, extract_blocks, pdf_author, render_cover
from backend.pdf.reflow import build_document
from backend.tts.engine import get_engine
from backend.tts.streamer import get_or_synthesize
from backend.tts.voices import DEFAULT_VOICE_ID
from backend.utils.logging import get_logger
from backend.utils.paths import audio_cache_path, book_upload_path, pdf_result_path

SUPPORTED_EXTS = (".pdf", ".epub")

logger = get_logger("api.pdf")
router = APIRouter(prefix="/api/pdf", tags=["pdf"])

_jobs: dict[str, dict[str, Any]] = {}
_audio_jobs: dict[str, dict[str, Any]] = {}
# Fila de áudio serial (um livro por vez na GPU, estilo Steam). A fonte da
# verdade é a lista _queued; o worker faz POLL dela (não bloqueia numa Queue),
# e é RE-INICIADO se morrer — assim a fila nunca fica presa "para sempre".
_queue_lock = threading.Lock()
_queued: list[str] = []            # job_ids aguardando (ordem = posição)
_audio_active: str | None = None   # job preparando agora
_cancelled: set[str] = set()       # jobs apagados que ainda podem estar na fila
_worker_thread: "threading.Thread | None" = None

_LIBRARY_PATH = CACHE_DIR / "pdf" / "_library.json"


def _cover_path(job_id: str) -> Path:
    return CACHE_DIR / "pdf" / f"{job_id}_cover.png"


# --------------------------------------------------------------------------- #
# Biblioteca persistente (índice em disco dos PDFs já processados)
# --------------------------------------------------------------------------- #
def _load_library() -> dict:
    try:
        return json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_library(data: dict) -> None:
    _LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LIBRARY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _library_put(job_id: str, **fields: Any) -> None:
    lib = _load_library()
    entry = lib.get(job_id, {})
    entry.update(fields)
    entry["job_id"] = job_id
    lib[job_id] = entry
    _save_library(lib)


def _cleaning_config_from_json(raw: str | None) -> CleaningConfig | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    cfg = CleaningConfig()
    for key, value in data.items():
        if hasattr(cfg, key) and isinstance(getattr(cfg, key), bool):
            setattr(cfg, key, bool(value))
    return cfg


def _collect_sentences(result: dict) -> list[str]:
    out: list[str] = []
    for sec in result.get("sections", []):
        for p in sec.get("paragraphs", []):
            for s in p.get("sentences", []):
                t = (s.get("text") or "").strip()
                if t:
                    out.append(t)
    return out


# --------------------------------------------------------------------------- #
# Pré-geração de áudio (aquece o cache para a leitura tocar sem travar)
# --------------------------------------------------------------------------- #
# Timeout por frase: uma frase normal leva ~7s; o pior caso do modelo (esgotar
# os tokens) ~40s. Acima de 75s a GPU/modelo travou — pulamos a frase para a
# fila NUNCA congelar. 3 travadas seguidas = wedge → aborta e recarrega o modelo.
_SYNTH_TIMEOUT = 75.0
_synth_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leia-synth")


def _pregen_audio(job_id: str, sentences: list[str]) -> None:
    global _synth_pool
    total = len(sentences)
    _audio_jobs[job_id] = {"status": "preparing", "done": 0, "total": total}
    if total == 0:
        _audio_jobs[job_id] = {"status": "done", "done": 0, "total": 0}
        _library_put(job_id, audio_ready=True)
        return
    # Carrega o modelo ANTES do loop, COM TIMEOUT. Se a GPU estiver sob pressão
    # e o load travar, o job vira "error" em vez de ficar 0% para sempre.
    if not get_engine().loaded:
        _audio_jobs[job_id]["phase"] = "loading"   # frontend: "Carregando a voz…"
    try:
        _synth_pool.submit(get_engine().ensure_loaded).result(timeout=180)
    except FuturesTimeout:
        logger.error("Modelo travou ao carregar (job %s) — GPU sobrecarregada? abortando.", job_id)
        _synth_pool.shutdown(wait=False, cancel_futures=True)
        _synth_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leia-synth")
        _audio_jobs[job_id] = {"status": "error", "done": 0, "total": total}
        _library_put(job_id, audio_ready=False)
        return
    except Exception:
        logger.exception("Falha ao carregar o modelo (job %s)", job_id)
    _audio_jobs[job_id] = {"status": "preparing", "done": 0, "total": total}

    done = failed = stalls = 0
    aborted = False
    for text in sentences:
        if job_id in _cancelled:   # livro apagado durante o preparo → para
            aborted = True
            break
        try:
            _synth_pool.submit(get_or_synthesize, text, DEFAULT_VOICE_ID, 1.0).result(
                timeout=_SYNTH_TIMEOUT
            )
            stalls = 0
        except FuturesTimeout:
            failed += 1
            stalls += 1
            logger.warning(
                "Frase travou (>%.0fs), pulando (job %s, %d seguidas)",
                _SYNTH_TIMEOUT, job_id, stalls,
            )
            # A thread travada não pode ser morta; troca o pool para as próximas.
            _synth_pool.shutdown(wait=False, cancel_futures=True)
            _synth_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leia-synth")
            if stalls >= 3:
                logger.error("Síntese travada; abortando job %s e recarregando o modelo.", job_id)
                try:
                    get_engine()._reload_locked()
                except Exception:
                    logger.exception("Falha ao recarregar o modelo")
                aborted = True
                break
        except Exception:
            failed += 1
            logger.exception("Pré-geração de áudio falhou numa frase (job %s)", job_id)
        done += 1
        _audio_jobs[job_id]["done"] = done

    # Livro apagado durante o preparo → não recria índice nem status.
    if job_id in _cancelled:
        _cancelled.discard(job_id)
        _audio_jobs.pop(job_id, None)
        logger.info("Preparo cancelado (livro apagado): job %s", job_id)
        return
    ok = (not aborted) and failed < total
    _audio_jobs[job_id]["status"] = "done" if ok else "error"
    _library_put(job_id, audio_ready=ok)
    logger.info(
        "Pré-geração de áudio: job %s (%d frases, %d falhas, abort=%s, ready=%s)",
        job_id, total, failed, aborted, ok,
    )


def _next_job() -> str | None:
    """Próximo job pendente da lista (descarta os cancelados/apagados)."""
    with _queue_lock:
        while _queued:
            cand = _queued[0]
            if cand in _cancelled:
                _queued.pop(0)
                _cancelled.discard(cand)
                _audio_jobs.pop(cand, None)
                continue
            return cand
    return None


def _audio_worker() -> None:
    """Consome a fila um livro por vez (serial → GPU não sobrecarrega).
    Faz POLL da lista _queued em vez de bloquear numa Queue — se esta thread
    morrer, o _ensure_worker()/watchdog cria outra e nada fica preso."""
    global _audio_active
    while True:
        job_id = _next_job()
        if job_id is None:
            time.sleep(0.4)
            continue
        try:
            _audio_active = job_id
            rp = pdf_result_path(job_id)
            if rp.exists():
                result = json.loads(rp.read_text(encoding="utf-8"))
                _pregen_audio(job_id, _collect_sentences(result))
            else:
                _audio_jobs.pop(job_id, None)  # sem resultado (apagado) → descarta
        except Exception:
            logger.exception("Erro na fila de áudio (job %s)", job_id)
            _audio_jobs[job_id] = {"status": "error", "done": 0, "total": 0}
        finally:
            _audio_active = None
            with _queue_lock:
                if job_id in _queued:
                    _queued.remove(job_id)


def _ensure_worker() -> None:
    """Garante que existe UM worker vivo. Chamado ao enfileirar e pelo watchdog."""
    global _worker_thread
    with _queue_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_audio_worker, daemon=True, name="leia-audio-queue"
        )
        _worker_thread.start()


def _queue_watchdog() -> None:
    """Se o worker morrer com fila pendente, ressuscita em segundos."""
    while True:
        time.sleep(5)
        try:
            if _queued and (_worker_thread is None or not _worker_thread.is_alive()):
                logger.warning("Worker de áudio caiu com fila pendente — reiniciando.")
                _ensure_worker()
        except Exception:
            pass


_ensure_worker()
threading.Thread(target=_queue_watchdog, daemon=True, name="leia-audio-watchdog").start()


def _enqueue_audio(job_id: str) -> bool:
    """Coloca um livro na fila de preparação de áudio (idempotente)."""
    if not pdf_result_path(job_id).exists():
        return False
    _cancelled.discard(job_id)
    if _audio_active == job_id:
        _ensure_worker()
        return True
    aj = _audio_jobs.get(job_id)
    if aj and aj.get("status") in ("queued", "preparing") and job_id in _queued:
        _ensure_worker()
        return True
    total = 0
    try:
        total = len(_collect_sentences(json.loads(pdf_result_path(job_id).read_text(encoding="utf-8"))))
    except Exception:
        pass
    _audio_jobs[job_id] = {"status": "queued", "done": 0, "total": total}
    with _queue_lock:
        if job_id not in _queued:
            _queued.append(job_id)
    _ensure_worker()
    return True


def _source_path(job_id: str) -> Path | None:
    ext = _load_library().get(job_id, {}).get("ext")
    if ext:
        p = book_upload_path(job_id, ext)
        if p.exists():
            return p
    for e in SUPPORTED_EXTS:
        p = book_upload_path(job_id, e)
        if p.exists():
            return p
    return None


def _make_cover(src_path: Path, ext: str, job_id: str) -> None:
    try:
        if ext == ".epub":
            extract_epub_cover(src_path, _cover_path(job_id))
        else:
            render_cover(src_path, _cover_path(job_id))
    except Exception:
        logger.exception("Falha ao gerar capa (job %s)", job_id)


def _process_book(
    job_id: str,
    src_path: Path,
    filename: str,
    ext: str,
    cfg: CleaningConfig | None = None,
    prepare: bool = False,
) -> None:
    try:
        _jobs[job_id] = {"status": "processing", "progress": 0.1, "filename": filename}
        if ext == ".epub":
            result = build_epub_document(src_path, filename)
        else:
            blocks = extract_blocks(src_path)
            _jobs[job_id]["progress"] = 0.6
            result = build_document(blocks, str(src_path), filename, cfg)
            result["metadata"]["author"] = pdf_author(src_path)
            result["raw_blocks_sample"] = blocks_as_jsonable(blocks[:20])
        result_path = pdf_result_path(job_id)
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        _jobs[job_id] = {
            "status": "done",
            "progress": 1.0,
            "filename": filename,
            "result_path": str(result_path),
        }
        _make_cover(src_path, ext, job_id)
        meta = result.get("metadata", {})
        _library_put(
            job_id,
            filename=filename,
            title=Path(filename).stem,
            author=meta.get("author", ""),
            ext=ext,
            pages=meta.get("pages", 0),
            chars=meta.get("extracted_chars", 0),
            created_at=time.time(),
            audio_ready=False,
        )
        # Só prepara o áudio se o usuário pediu (opt-in). Vai para a fila serial.
        if prepare:
            _enqueue_audio(job_id)
        logger.info("Book job %s done (%s, prepare=%s)", job_id, filename, prepare)
    except Exception as exc:
        logger.exception("Book job %s failed", job_id)
        _jobs[job_id] = {
            "status": "error",
            "progress": 1.0,
            "filename": filename,
            "error": str(exc),
        }


@router.post("/upload")
async def upload_pdf(
    file: UploadFile,
    background: BackgroundTasks,
    cleaning: str | None = Form(default=None),
    prepare: bool = Form(default=False),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf ou .epub")

    job_id = uuid.uuid4().hex[:12]
    target = book_upload_path(job_id, ext)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    target.write_bytes(data)

    cfg = _cleaning_config_from_json(cleaning)
    _jobs[job_id] = {"status": "queued", "progress": 0.0, "filename": file.filename}
    background.add_task(_process_book, job_id, target, file.filename, ext, cfg, prepare)
    return {"job_id": job_id, "filename": file.filename, "size_bytes": len(data)}


@router.get("/library")
def library():
    lib = _load_library()
    items = []
    for jid, e in lib.items():
        if not pdf_result_path(jid).exists():
            continue
        # backfill de 'chars'/'author' para livros antigos
        if not e.get("chars") or e.get("author") is None:
            try:
                meta = json.loads(pdf_result_path(jid).read_text(encoding="utf-8")).get("metadata", {})
                _library_put(jid, chars=meta.get("extracted_chars", 0), author=meta.get("author", ""))
                e = _load_library().get(jid, e)
            except Exception:
                pass
        aj = _audio_jobs.get(jid)
        if aj:
            audio = {"status": aj.get("status"), "done": aj.get("done", 0), "total": aj.get("total", 0)}
        elif e.get("audio_ready"):
            audio = {"status": "done", "done": 1, "total": 1}
        else:
            audio = {"status": "none", "done": 0, "total": 0}  # não preparado
        items.append(
            {
                "job_id": jid,
                "filename": e.get("filename", "PDF"),
                "title": e.get("title") or e.get("filename", "PDF"),
                "author": e.get("author", ""),
                "pages": e.get("pages", 0),
                "chars": e.get("chars", 0),
                "created_at": e.get("created_at"),
                "last_opened": e.get("last_opened"),
                "collection": e.get("collection", ""),
                "source": e.get("source", ""),
                "source_warning": e.get("source_warning", ""),
                "progress": e.get("progress", -1),
                "progress_total": e.get("progress_total", 0),
                "audio_ready": bool(e.get("audio_ready")),
                "audio": audio,
            }
        )
    items.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return {"items": items}


@router.get("/{job_id}/cover")
def job_cover(job_id: str):
    p = _cover_path(job_id)
    if not p.exists():
        # backfill: gera a capa sob demanda a partir do arquivo original
        src = _source_path(job_id)
        if src:
            _make_cover(src, src.suffix.lower(), job_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Sem capa")
    return FileResponse(str(p), media_type="image/png")


@router.get("/{job_id}/status")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if job:
        return job
    # Fallback em disco: documento da biblioteca reaberto após reiniciar o backend.
    if pdf_result_path(job_id).exists():
        lib = _load_library().get(job_id, {})
        return {
            "status": "done",
            "progress": 1.0,
            "filename": lib.get("filename", "PDF"),
            "result_path": str(pdf_result_path(job_id)),
        }
    raise HTTPException(status_code=404, detail="Job não encontrado")


@router.get("/{job_id}/audio-status")
def audio_status(job_id: str):
    j = _audio_jobs.get(job_id)
    if j:
        out = dict(j)
        if j.get("status") == "queued" and job_id in _queued:
            out["position"] = _queued.index(job_id) + 1
        return out
    if _load_library().get(job_id, {}).get("audio_ready"):
        return {"status": "done", "done": 1, "total": 1}
    return {"status": "none", "done": 0, "total": 0}  # áudio ainda não preparado


@router.post("/{job_id}/prepare")
def prepare_audio(job_id: str):
    if job_id not in _load_library() and not pdf_result_path(job_id).exists():
        raise HTTPException(status_code=404, detail="Livro não encontrado")
    if not _enqueue_audio(job_id):
        raise HTTPException(status_code=400, detail="Não foi possível preparar o áudio")
    pos = (_queued.index(job_id) + 1) if job_id in _queued else 0
    return {"ok": True, "status": _audio_jobs.get(job_id, {}).get("status", "queued"), "position": pos}


@router.get("/queue")
def audio_queue_state():
    lib = _load_library()

    def entry(jid: str, status: str) -> dict:
        aj = _audio_jobs.get(jid, {})
        e = lib.get(jid, {})
        return {
            "job_id": jid,
            "title": e.get("title") or e.get("filename", "PDF"),
            "status": status,
            "done": aj.get("done", 0),
            "total": aj.get("total", 0),
        }

    items = []
    if _audio_active:
        items.append(entry(_audio_active, "preparing"))
    for jid in list(_queued):
        items.append(entry(jid, "queued"))
    return {"active": _audio_active, "count": len(items), "items": items}


@router.get("/{job_id}/result")
def job_result(job_id: str):
    path = pdf_result_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Resultado não encontrado")
    if _load_library().get(job_id):
        _library_put(job_id, last_opened=time.time())  # histórico de leitura
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


class ProgressBody(BaseModel):
    index: int = 0
    total: int = 0


@router.post("/{job_id}/progress")
def save_progress(job_id: str, body: ProgressBody):
    """Salva o ponto de leitura NO DISCO (sobrevive a fechamento brusco/queda
    de energia — não depende só do localStorage do navegador)."""
    if job_id not in _load_library():
        raise HTTPException(status_code=404, detail="Livro não encontrado")
    fields = {"progress": max(0, int(body.index)), "last_opened": time.time()}
    if body.total:
        fields["progress_total"] = int(body.total)
    _library_put(job_id, **fields)
    return {"ok": True, "progress": fields["progress"]}


@router.get("/{job_id}/progress")
def get_progress(job_id: str):
    e = _load_library().get(job_id, {})
    return {"index": e.get("progress", -1), "total": e.get("progress_total", 0)}


class CollectionBody(BaseModel):
    collection: str = ""


@router.post("/{job_id}/collection")
def set_collection(job_id: str, body: CollectionBody):
    if job_id not in _load_library():
        raise HTTPException(status_code=404, detail="Livro não encontrado")
    _library_put(job_id, collection=body.collection.strip())
    return {"ok": True, "collection": body.collection.strip()}


@router.get("/search")
def search(q: str = ""):
    ql = (q or "").strip().lower()
    if len(ql) < 2:
        return {"results": []}
    lib = _load_library()
    results = []
    for jid, e in lib.items():
        if not pdf_result_path(jid).exists():
            continue
        in_title = ql in (e.get("title") or "").lower()
        in_author = ql in (e.get("author") or "").lower()
        snippet = None
        try:
            data = json.loads(pdf_result_path(jid).read_text(encoding="utf-8"))
            for sec in data.get("sections", []):
                for p in sec.get("paragraphs", []):
                    t = p.get("text", "")
                    i = t.lower().find(ql)
                    if i >= 0:
                        a = max(0, i - 40)
                        snippet = ("…" if a > 0 else "") + t[a:i + len(ql) + 60].strip() + "…"
                        break
                if snippet:
                    break
        except Exception:
            pass
        if in_title or in_author or snippet:
            results.append({
                "job_id": jid,
                "title": e.get("title"),
                "author": e.get("author", ""),
                "in_title": in_title,
                "in_author": in_author,
                "snippet": snippet,
            })
    return {"results": results}


@router.delete("/{job_id}")
def delete_doc(job_id: str):
    # 1) apaga o áudio cacheado deste livro (frases → arquivos de cache)
    rp = pdf_result_path(job_id)
    if rp.exists():
        try:
            result = json.loads(rp.read_text(encoding="utf-8"))
            for text in _collect_sentences(result):
                try:
                    audio_cache_path(text, DEFAULT_VOICE_ID, 1.0).unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception:
            logger.exception("Falha ao apagar áudio do job %s", job_id)
    # 2) índice + arquivos (resultado, capa, original)
    lib = _load_library()
    lib.pop(job_id, None)
    _save_library(lib)
    paths = [rp, _cover_path(job_id)]
    src = _source_path(job_id)
    if src:
        paths.append(src)
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    _jobs.pop(job_id, None)
    _audio_jobs.pop(job_id, None)
    # 3) tira da fila de narração (evita "fantasma" na fila); se estiver ativo,
    #    marca como cancelado para o worker parar e não recriar o índice.
    with _queue_lock:
        if job_id in _queued:
            _queued.remove(job_id)
    _cancelled.add(job_id)
    return {"ok": True}


@router.post("/extract-sync")
async def extract_sync(file: UploadFile):
    """Synchronous PDF extraction — handy for dev and tests."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")
    job_id = uuid.uuid4().hex[:12]
    target = book_upload_path(job_id, ".pdf")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    target.write_bytes(data)
    try:
        blocks = extract_blocks(target)
        return build_document(blocks, str(target), file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
