from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.tts.engine import wav_duration_seconds
from backend.tts.streamer import get_or_synthesize, split_sentences
from backend.tts.voices import DEFAULT_VOICE_ID, resolve_voice
from backend.utils.logging import get_logger

logger = get_logger("api.tts")
router = APIRouter(tags=["tts"])


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str = DEFAULT_VOICE_ID
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@router.post("/api/tts/synthesize")
def synthesize(req: SynthesizeRequest):
    try:
        resolve_voice(req.voice)
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
    """WebSocket de streaming.

    Cliente envia:
      { "text": "...", "voice": "ana_florence", "speed": 1.0,
        "sentence_ids": ["p_3_s_0", "p_3_s_1", ...]  # opcional, mesmo tamanho de split }

    Servidor envia:
      { "type": "plan", "sentences": [{ "id": "p_3_s_0", "text": "..." }, ...] }
      { "type": "audio_chunk", "sentence_id": "...", "index": 0, "audio_b64": "...", "mime": "audio/wav" }
      { "type": "sentence_done", "sentence_id": "...", "duration_ms": 3420 }
      { "type": "section_done" }
      { "type": "error", "message": "..." }
    """
    await ws.accept()
    try:
        payload: dict[str, Any] = await ws.receive_json()
        text = (payload.get("text") or "").strip()
        voice = payload.get("voice", DEFAULT_VOICE_ID)
        speed = float(payload.get("speed", 1.0))
        sentence_ids = payload.get("sentence_ids") or []

        if not text:
            await ws.send_json({"type": "error", "message": "Texto vazio"})
            return
        try:
            resolve_voice(voice)
        except KeyError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            return

        sentences = split_sentences(text)
        if len(sentence_ids) != len(sentences):
            sentence_ids = [f"s_{i}" for i in range(len(sentences))]

        await ws.send_json(
            {
                "type": "plan",
                "sentences": [
                    {"id": sid, "text": s} for sid, s in zip(sentence_ids, sentences)
                ],
            }
        )

        for i, (sid, sentence) in enumerate(zip(sentence_ids, sentences)):
            try:
                wav = get_or_synthesize(sentence, voice, speed)
            except Exception as exc:
                logger.exception("Falha sintetizando sentença %s", sid)
                await ws.send_json(
                    {"type": "error", "sentence_id": sid, "message": str(exc)}
                )
                continue
            duration_ms = int(wav_duration_seconds(wav) * 1000)
            await ws.send_json(
                {
                    "type": "audio_chunk",
                    "sentence_id": sid,
                    "index": i,
                    "audio_b64": base64.b64encode(wav).decode("ascii"),
                    "mime": "audio/wav",
                    "duration_ms": duration_ms,
                }
            )
            await ws.send_json(
                {"type": "sentence_done", "sentence_id": sid, "duration_ms": duration_ms}
            )

        await ws.send_json({"type": "section_done"})
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
