from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.config import CACHE_DIR
from backend.epub.extractor import build_epub_document, extract_epub_cover
from backend.pdf.cleaner import CleaningConfig
from backend.pdf.extractor import blocks_as_jsonable, extract_blocks, render_cover
from backend.pdf.reflow import build_document
from backend.tts.streamer import get_or_synthesize
from backend.tts.voices import DEFAULT_VOICE_ID
from backend.utils.logging import get_logger
from backend.utils.paths import audio_cache_path, book_upload_path, pdf_result_path

SUPPORTED_EXTS = (".pdf", ".epub")

logger = get_logger("api.pdf")
router = APIRouter(prefix="/api/pdf", tags=["pdf"])

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict[str, Any]] = {}
_audio_jobs: dict[str, dict[str, Any]] = {}

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
def _pregen_audio(job_id: str, sentences: list[str]) -> None:
    total = len(sentences)
    _audio_jobs[job_id] = {"status": "preparing", "done": 0, "total": total}
    if total == 0:
        _audio_jobs[job_id] = {"status": "done", "done": 0, "total": 0}
        _library_put(job_id, audio_ready=True)
        return
    done = 0
    failed = 0
    for text in sentences:
        try:
            get_or_synthesize(text, DEFAULT_VOICE_ID, 1.0)
        except Exception:
            failed += 1
            logger.exception("Pré-geração de áudio falhou numa frase (job %s)", job_id)
        done += 1
        _audio_jobs[job_id]["done"] = done
    # Só marca "pronto" se a síntese realmente funcionou (não esconde falha sistêmica).
    ok = failed < total
    _audio_jobs[job_id]["status"] = "done" if ok else "error"
    _library_put(job_id, audio_ready=ok)
    logger.info(
        "Pré-geração de áudio: job %s (%d frases, %d falhas, ready=%s)", job_id, total, failed, ok
    )


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
    job_id: str, src_path: Path, filename: str, ext: str, cfg: CleaningConfig | None = None
) -> None:
    try:
        _jobs[job_id] = {"status": "processing", "progress": 0.1, "filename": filename}
        if ext == ".epub":
            result = build_epub_document(src_path, filename)
        else:
            blocks = extract_blocks(src_path)
            _jobs[job_id]["progress"] = 0.6
            result = build_document(blocks, str(src_path), filename, cfg)
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
            ext=ext,
            pages=meta.get("pages", 0),
            chars=meta.get("extracted_chars", 0),
            created_at=time.time(),
            audio_ready=False,
        )
        # Aquece o cache de áudio em background para a leitura ser instantânea.
        _executor.submit(_pregen_audio, job_id, _collect_sentences(result))
        logger.info("Book job %s done (%s)", job_id, filename)
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
    background.add_task(_process_book, job_id, target, file.filename, ext, cfg)
    return {"job_id": job_id, "filename": file.filename, "size_bytes": len(data)}


@router.get("/library")
def library():
    lib = _load_library()
    items = []
    for jid, e in lib.items():
        if not pdf_result_path(jid).exists():
            continue
        # backfill de 'chars' para livros antigos (estimativa de tempo na estante)
        if not e.get("chars"):
            try:
                meta = json.loads(pdf_result_path(jid).read_text(encoding="utf-8")).get("metadata", {})
                _library_put(jid, chars=meta.get("extracted_chars", 0))
                e = _load_library().get(jid, e)
            except Exception:
                pass
        aj = _audio_jobs.get(jid)
        if aj:
            audio = {"status": aj.get("status"), "done": aj.get("done", 0), "total": aj.get("total", 0)}
        elif e.get("audio_ready"):
            audio = {"status": "done", "done": 1, "total": 1}
        else:
            audio = {"status": "unknown", "done": 0, "total": 0}
        items.append(
            {
                "job_id": jid,
                "filename": e.get("filename", "PDF"),
                "title": e.get("title") or e.get("filename", "PDF"),
                "pages": e.get("pages", 0),
                "chars": e.get("chars", 0),
                "created_at": e.get("created_at"),
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


def _ensure_pregen(job_id: str) -> bool:
    """Garante a pré-geração rodando (retoma após o backend reiniciar). Idempotente:
    frases já cacheadas são puladas. Retorna True se está preparando ou pronta."""
    aj = _audio_jobs.get(job_id)
    if aj and aj.get("status") in ("preparing", "done"):
        return True
    if _load_library().get(job_id, {}).get("audio_ready"):
        return True
    path = pdf_result_path(job_id)
    if not path.exists():
        return False
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    _executor.submit(_pregen_audio, job_id, _collect_sentences(result))
    return True


@router.get("/{job_id}/audio-status")
def audio_status(job_id: str):
    j = _audio_jobs.get(job_id)
    if j:
        return j
    if _load_library().get(job_id, {}).get("audio_ready"):
        return {"status": "done", "done": 1, "total": 1}
    if _ensure_pregen(job_id):
        return _audio_jobs.get(job_id) or {"status": "preparing", "done": 0, "total": 0}
    return {"status": "unknown", "done": 0, "total": 0}


@router.get("/{job_id}/result")
def job_result(job_id: str):
    path = pdf_result_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Resultado não encontrado")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


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
