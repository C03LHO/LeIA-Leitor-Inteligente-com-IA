from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient

import backend.api.routes_tts as routes_tts
from backend.api.routes_pdf import _cleaning_config_from_json
from backend.main import app


def _fake_wav(seconds: float = 0.1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))
    return buf.getvalue()


def test_ws_respects_client_sentence_ids(monkeypatch):
    """O WS deve devolver os mesmos ids que o cliente enviou (1:1), sem re-dividir."""
    monkeypatch.setattr(routes_tts, "get_or_synthesize", lambda text, voice, speed: _fake_wav())
    client = TestClient(app)
    sent = [
        {"id": "s0_p0_0", "text": "Olá, leitor."},
        {"id": "s0_p0_1", "text": "Tudo bem com você?"},
        {"id": "s0_p1_0", "text": "Terceira frase, outro parágrafo."},
    ]
    with client.websocket_connect("/ws/tts") as ws:
        ws.send_json({"sentences": sent, "voice": "ana_florence", "speed": 1.0})
        plan = ws.receive_json()
        assert plan["type"] == "plan"
        assert [s["id"] for s in plan["sentences"]] == ["s0_p0_0", "s0_p0_1", "s0_p1_0"]

        chunk_ids = []
        while True:
            msg = ws.receive_json()
            if msg["type"] == "audio_chunk":
                chunk_ids.append(msg["sentence_id"])
            elif msg["type"] == "section_done":
                break
            elif msg["type"] == "error":
                raise AssertionError(f"WS erro inesperado: {msg}")
        assert chunk_ids == ["s0_p0_0", "s0_p0_1", "s0_p1_0"]


def test_ws_fallback_splits_raw_text(monkeypatch):
    """Sem 'sentences', o WS ainda divide o texto cru (caminho de compatibilidade)."""
    monkeypatch.setattr(routes_tts, "get_or_synthesize", lambda text, voice, speed: _fake_wav())
    client = TestClient(app)
    with client.websocket_connect("/ws/tts") as ws:
        ws.send_json({"text": "Primeira. Segunda. Terceira.", "voice": "ana_florence"})
        plan = ws.receive_json()
        assert plan["type"] == "plan"
        assert len(plan["sentences"]) == 3


def test_cleaning_config_from_json_overrides_only_known_bools():
    cfg = _cleaning_config_from_json('{"remove_footnotes": false, "inexistente": 1}')
    assert cfg is not None
    assert cfg.remove_footnotes is False
    assert cfg.remove_urls is True  # default preservado
    assert not hasattr(cfg, "inexistente")


def test_cleaning_config_from_json_handles_garbage():
    assert _cleaning_config_from_json(None) is None
    assert _cleaning_config_from_json("não é json") is None
    assert _cleaning_config_from_json("[1,2,3]") is None
