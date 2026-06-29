from __future__ import annotations

import pytest

from backend.tts.engine import detect_hardware, get_engine, wav_duration_seconds
from backend.tts.streamer import merge_enumerators, split_sentences
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


def test_single_native_voice():
    assert len(EMBEDDED_VOICES) == 1
    assert EMBEDDED_VOICES[0].id == DEFAULT_VOICE_ID
    assert len(all_voices()) == 1


def test_resolve_voice_default():
    v = resolve_voice(DEFAULT_VOICE_ID)
    assert v.language == "pt"
    assert v.id == DEFAULT_VOICE_ID


def test_resolve_voice_unknown_falls_back_to_default():
    # Voz única: ids desconhecidos (ex.: prefs antigas do XTTS) caem na padrão.
    v = resolve_voice("ana_florence")
    assert v.id == DEFAULT_VOICE_ID


def test_get_engine_singleton():
    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_split_sentences_handles_pt_punct():
    out = split_sentences("Boa noite, leitor. Como vai você? Estou bem!")
    assert len(out) == 3


def test_merge_enumerators_joins_lone_markers():
    assert merge_enumerators(["4.", "São eles:"]) == ["4. São eles:"]
    assert merge_enumerators(["(1)", "A Lei Moral."]) == ["(1) A Lei Moral."]
    assert merge_enumerators(["5–6.", "A Lei Moral."]) == ["5–6. A Lei Moral."]
    assert merge_enumerators(["Texto normal."]) == ["Texto normal."]
    assert merge_enumerators(["7."]) == ["7."]  # sozinho no fim, permanece


def test_engine_load_optional():
    engine = get_engine()
    try:
        engine.ensure_loaded()
    except Exception:
        pytest.skip("Chatterbox não disponível no ambiente de teste")


def test_synthesize_skips_degenerate_text():
    engine = get_engine()
    try:
        engine.ensure_loaded()
    except Exception:
        pytest.skip("Chatterbox não disponível no ambiente de teste")
    # "4." não tem conteúdo falável → silêncio curto, sem chamar o modelo (sem crash CUDA)
    wav = engine.synthesize("4.")
    assert wav_duration_seconds(wav) < 0.5
