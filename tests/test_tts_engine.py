from __future__ import annotations

import pytest

from backend.tts.engine import detect_hardware, get_engine
from backend.tts.streamer import split_sentences
from backend.tts.voices import builtin_voices, get_voice


def test_detect_hardware_returns_struct():
    hw = detect_hardware()
    assert hw.device in ("cuda", "cpu")
    assert isinstance(hw.cuda_available, bool)


def test_builtin_voices_default():
    voices = builtin_voices()
    assert any(v.id == "default" for v in voices)
    v = get_voice("default")
    assert v.language == "pt"


def test_get_engine_singleton():
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_split_sentences_handles_pt_punct():
    out = split_sentences("Boa noite, leitor. Como vai você? Estou bem!")
    assert len(out) == 3


def test_engine_load_optional():
    """O modelo XTTS é pesado e pode não estar instalado em CI.
    Quando não estiver, ensure_loaded() levanta — toleramos ambas as situações."""
    engine = get_engine()
    try:
        engine.ensure_loaded()
    except Exception:
        pytest.skip("XTTS-v2 não disponível no ambiente de teste")
