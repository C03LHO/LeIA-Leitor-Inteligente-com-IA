from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from backend.config import FRONTEND_DIR
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

# Amostras pré-geradas e embutidas → o preview toca NA HORA, sem precisar da GPU
# (antes a 1ª amostra levava minutos: carregava o modelo e sintetizava na hora).
_PREVIEW_DIR = FRONTEND_DIR / "previews"


def voice_slug(voice_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", voice_id.lower()).strip("_")


def preview_file(voice_id: str) -> Path:
    return _PREVIEW_DIR / f"{voice_slug(voice_id)}.wav"


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
    # 1) amostra embutida → resposta imediata, sem GPU
    pre = preview_file(vid)
    if pre.exists():
        return FileResponse(str(pre), media_type="audio/wav")
    # 2) fallback: sintetiza sob demanda (voz sem amostra pronta)
    try:
        wav = get_or_synthesize(PREVIEW_SENTENCE, vid, 1.0)
    except Exception as exc:
        logger.exception("Falha no preview da voz %s", vid)
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=wav, media_type="audio/wav")
