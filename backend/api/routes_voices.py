from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.tts.streamer import get_or_synthesize
from backend.tts.voices import PREVIEW_SENTENCE, all_voices
from backend.utils.logging import get_logger

logger = get_logger("api.voices")
router = APIRouter(prefix="/api/voices", tags=["voices"])


@router.get("")
def list_voices():
    return {"voices": [v.to_dict() for v in all_voices()]}


@router.post("/{voice_id}/preview")
def preview_voice(voice_id: str):
    try:
        wav = get_or_synthesize(PREVIEW_SENTENCE, voice_id, 1.0)
    except Exception as exc:
        logger.exception("Falha no preview da voz %s", voice_id)
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=wav, media_type="audio/wav")
