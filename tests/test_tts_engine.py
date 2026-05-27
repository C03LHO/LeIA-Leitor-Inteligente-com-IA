from __future__ import annotations

import pytest

from backend.tts.engine import detect_hardware, get_engine
from backend.tts.streamer import split_sentences
from backend.tts.voices import (
    DEFAULT_VOICE_ID,
    EMBEDDED_VOICES,
    all_voices,
    resolve_voice,
)


def test_detect_hardware_returns_struct():
    hw = detect_hardware()
    assert hw.device in ("cuda", "cpu")
    assert isinstance(hw.cuda_available, bool)


def test_embedded_catalog_has_ten_voices():
    assert len(EMBEDDED_VOICES) == 10
    ids = [v.id for v in EMBEDDED_VOICES]
    assert len(set(ids)) == 10
    assert DEFAULT_VOICE_ID in ids


def test_resolve_voice_default():
    v = resolve_voice(DEFAULT_VOICE_ID)
    assert v.language == "pt"
    assert v.kind == "embedded"
    assert v.speaker


def test_resolve_voice_unknown_raises():
    with pytest.raises(KeyError):
        resolve_voice("does_not_exist")


def test_all_voices_includes_embedded():
    voices = all_voices()
    assert len(voices) >= 10


def test_get_engine_singleton():
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_split_sentences_handles_pt_punct():
    out = split_sentences("Boa noite, leitor. Como vai você? Estou bem!")
    assert len(out) == 3


def test_engine_load_optional():
    engine = get_engine()
    try:
        engine.ensure_loaded()
    except Exception:
        pytest.skip("XTTS-v2 não disponível no ambiente de teste")
