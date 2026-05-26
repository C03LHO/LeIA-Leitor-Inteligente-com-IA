from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.pdf.extractor import blocks_as_jsonable, extract_blocks
from backend.pdf.reflow import build_document
from backend.utils.logging import get_logger
from backend.utils.paths import pdf_result_path, pdf_upload_path

logger = get_logger("api.pdf")
router = APIRouter(prefix="/api/pdf", tags=["pdf"])

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict[str, Any]] = {}


def _process_pdf(job_id: str, pdf_path: Path, filename: str) -> None:
    try:
        _jobs[job_id] = {"status": "processing", "progress": 0.1, "filename": filename}
        blocks = extract_blocks(pdf_path)
        _jobs[job_id]["progress"] = 0.6
        result = build_document(blocks, str(pdf_path), filename)
        result["raw_blocks_sample"] = blocks_as_jsonable(blocks[:20])
        result_path = pdf_result_path(job_id)
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        _jobs[job_id] = {
            "status": "done",
            "progress": 1.0,
            "filename": filename,
            "result_path": str(result_path),
        }
        logger.info("PDF job %s done (%s)", job_id, filename)
    except Exception as exc:
        logger.exception("PDF job %s failed", job_id)
        _jobs[job_id] = {
            "status": "error",
            "progress": 1.0,
            "filename": filename,
            "error": str(exc),
        }


@router.post("/upload")
async def upload_pdf(file: UploadFile, background: BackgroundTasks):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")

    job_id = uuid.uuid4().hex[:12]
    target = pdf_upload_path(job_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    target.write_bytes(data)

    _jobs[job_id] = {"status": "queued", "progress": 0.0, "filename": file.filename}
    background.add_task(_process_pdf, job_id, target, file.filename)
    return {"job_id": job_id, "filename": file.filename, "size_bytes": len(data)}


@router.get("/{job_id}/status")
def job_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job


@router.get("/{job_id}/result")
def job_result(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job está com status: {job['status']}")
    path = Path(job["result_path"])
    if not path.exists():
        raise HTTPException(status_code=500, detail="Resultado ausente em disco")
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@router.post("/extract-sync")
async def extract_sync(file: UploadFile):
    """Synchronous PDF extraction — handy for dev and tests."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .pdf")
    job_id = uuid.uuid4().hex[:12]
    target = pdf_upload_path(job_id)
    data = await file.read()
    target.write_bytes(data)
    blocks = extract_blocks(target)
    result = build_document(blocks, str(target), file.filename)
    return result
