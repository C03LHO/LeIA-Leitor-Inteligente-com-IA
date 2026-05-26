from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.tts.streamer import get_or_synthesize, split_sentences
from backend.tts.voices import builtin_voices, get_voice
from backend.utils.logging import get_logger

logger = get_logger("api.tts")
router = APIRouter(tags=["tts"])


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = "default"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@router.get("/api/voices")
def list_voices():
    return {"voices": [v.to_dict() for v in builtin_voices()]}


@router.post("/api/tts/synthesize")
def synthesize(req: SynthesizeRequest):
    try:
        get_voice(req.voice)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        wav = get_or_synthesize(req.text, req.voice, req.speed)
    except Exception as exc:
        logger.exception("Falha na síntese TTS")
        raise HTTPException(status_code=500, detail=str(exc))
    return Response(content=wav, media_type="audio/wav")


@router.websocket("/ws/tts")
async def tts_stream(ws: WebSocket) -> None:
    await ws.accept()
    try:
        payload: dict[str, Any] = await ws.receive_json()
        text = payload.get("text", "").strip()
        voice = payload.get("voice", "default")
        speed = float(payload.get("speed", 1.0))
        if not text:
            await ws.send_json({"type": "error", "message": "Texto vazio"})
            await ws.close()
            return
        try:
            get_voice(voice)
        except KeyError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close()
            return

        sentences = split_sentences(text)
        await ws.send_json({"type": "plan", "sentences": sentences})

        for i, sentence in enumerate(sentences):
            try:
                wav = get_or_synthesize(sentence, voice, speed)
            except Exception as exc:
                logger.exception("Falha sintetizando sentença %d", i)
                await ws.send_json({"type": "error", "index": i, "message": str(exc)})
                continue
            await ws.send_json(
                {
                    "type": "chunk",
                    "index": i,
                    "sentence": sentence,
                    "audio_b64": base64.b64encode(wav).decode("ascii"),
                    "mime": "audio/wav",
                }
            )
        await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("Cliente WS encerrou a conexão")
    except Exception:
        logger.exception("Erro no WS de TTS")
        try:
            await ws.send_json({"type": "error", "message": "Erro interno"})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
