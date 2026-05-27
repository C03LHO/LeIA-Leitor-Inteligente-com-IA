from __future__ import annotations

import io
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response

from backend.tts.engine import get_engine, wav_duration_seconds
from backend.tts.streamer import get_or_synthesize
from backend.tts.voices import (
    PREVIEW_SENTENCE,
    add_custom_voice,
    all_voices,
    remove_custom_voice,
    resolve_voice,
)
from backend.utils.logging import get_logger

logger = get_logger("api.voices")
router = APIRouter(prefix="/api/voices", tags=["voices"])

MIN_DURATION = 6.0
MAX_DURATION = 30.0
MAX_BYTES = 5 * 1024 * 1024


@router.get("")
def list_voices():
    return {"voices": [v.to_dict() for v in all_voices()]}


@router.post("/upload")
async def upload_voice(file: UploadFile, name: str = ""):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Arquivo maior que 5 MB")
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .wav")

    duration, channels, sample_rate = _inspect_wav(raw)
    if duration < MIN_DURATION or duration > MAX_DURATION:
        raise HTTPException(
            status_code=400,
            detail=f"Duração deve estar entre {MIN_DURATION:.0f}s e {MAX_DURATION:.0f}s "
            f"(recebido {duration:.1f}s)",
        )
    if channels != 1:
        raise HTTPException(status_code=400, detail="WAV deve ser mono")
    if sample_rate < 22050:
        raise HTTPException(status_code=400, detail="Taxa de amostragem deve ser ≥ 22050 Hz")

    display_name = name.strip() or Path(file.filename).stem
    voice = add_custom_voice(raw, display_name, duration_s=duration)
    return voice.to_dict()


@router.delete("/{voice_id}")
def delete_voice(voice_id: str):
    if not voice_id.startswith("custom_"):
        raise HTTPException(status_code=400, detail="Só é possível remover vozes personalizadas")
    if not remove_custom_voice(voice_id):
        raise HTTPException(status_code=404, detail="Voz não encontrada")
    return {"ok": True}


@router.post("/{voice_id}/preview")
def preview_voice(voice_id: str):
    try:
        resolve_voice(voice_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Voz não encontrada")
    try:
        wav = get_or_synthesize(PREVIEW_SENTENCE, voice_id, 1.0)
    except Exception as exc:
        logger.exception("Falha no preview da voz %s", voice_id)
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=wav, media_type="audio/wav")


def _inspect_wav(raw: bytes) -> tuple[float, int, int]:
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            frames = wf.getnframes()
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            duration = frames / float(sample_rate or 1)
            return duration, channels, sample_rate
    except wave.Error as exc:
        raise HTTPException(status_code=400, detail=f"WAV inválido: {exc}")
