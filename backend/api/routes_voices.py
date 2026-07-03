from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.tts.streamer import get_or_synthesize
from backend.tts.voices import (
    PREVIEW_SENTENCE,
    RECOMMENDED_VOICE_IDS,
    all_voices,
    get_active_voice_id,
    resolve_voice,
    set_active_voice_id,
)
from backend.utils.logging import get_logger

logger = get_logger("api.voices")
router = APIRouter(prefix="/api/voices", tags=["voices"])


@router.get("")
def list_voices():
    active = get_active_voice_id()
    voices = []
    for v in all_voices():
        d = v.to_dict()
        d["recommended"] = v.id in RECOMMENDED_VOICE_IDS
        d["active"] = v.id == active
        voices.append(d)
    return {"voices": voices, "active": active}


class VoiceBody(BaseModel):
    voice: str


@router.post("/active")
def set_voice(body: VoiceBody):
    vid = set_active_voice_id(body.voice)
    return {"ok": True, "active": vid}


@router.post("/{voice_id}/preview")
def preview_voice(voice_id: str):
    vid = resolve_voice(voice_id).id
    try:
        wav = get_or_synthesize(PREVIEW_SENTENCE, vid, 1.0)
    except Exception as exc:
        logger.exception("Falha no preview da voz %s", vid)
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=wav, media_type="audio/wav")
