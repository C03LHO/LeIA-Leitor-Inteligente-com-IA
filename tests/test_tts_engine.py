from __future__ import annotations

import pytest

from backend.tts.engine import (
    _sanitize_text,
    detect_hardware,
    get_engine,
    wav_duration_seconds,
)
from backend.tts.streamer import merge_enumerators, split_sentences
from backend.tts.voices import (
    DEFAULT_VOICE_ID,
    EMBEDDED_VOICES,
    RECOMMENDED_VOICE_IDS,
    all_voices,
    resolve_voice,
)


def test_detect_hardware_returns_struct():
    hw = detect_hardware()
    assert hw.device in ("cuda", "cpu")
    assert isinstance(hw.cuda_available, bool)


def test_voice_catalog():
    # Catálogo XTTS: várias vozes embutidas; a padrão existe e é recomendada.
    ids = [v.id for v in all_voices()]
    assert len(EMBEDDED_VOICES) >= 1
    assert DEFAULT_VOICE_ID in ids
    assert DEFAULT_VOICE_ID in RECOMMENDED_VOICE_IDS


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


def test_split_keeps_abbreviations_together():
    # O ponto de "Dr."/"Dra." não pode encerrar frase.
    out = split_sentences("O Dr. Silva e a Dra. Souza saíram. Depois voltaram.")
    assert out == ["O Dr. Silva e a Dra. Souza saíram.", "Depois voltaram."]


def test_split_keeps_seculo_with_roman_numeral():
    # "séc. XX" precisa ficar na mesma frase (senão o romano vira órfão).
    out = split_sentences("Foi no séc. XX. Um marco histórico.")
    assert out[0] == "Foi no séc. XX."


def test_split_does_not_break_numbers_or_initials():
    assert split_sentences("Custou 3.14 e 1.234 reais. Fim.") == ["Custou 3.14 e 1.234 reais.", "Fim."]
    assert split_sentences("J. R. R. Tolkien escreveu. Foi genial.")[0] == "J. R. R. Tolkien escreveu."


def test_merge_enumerators_joins_lone_markers():
    assert merge_enumerators(["4.", "São eles:"]) == ["4. São eles:"]
    assert merge_enumerators(["(1)", "A Lei Moral."]) == ["(1) A Lei Moral."]
    assert merge_enumerators(["5–6.", "A Lei Moral."]) == ["5–6. A Lei Moral."]
    assert merge_enumerators(["Texto normal."]) == ["Texto normal."]
    assert merge_enumerators(["7."]) == ["7."]  # sozinho no fim, permanece


def test_sanitize_keeps_clean_portuguese():
    assert _sanitize_text("O menino correu para casa.") == "O menino correu para casa."
    # Ordinais são lidos por extenso (números por extenso, Fase A).
    assert _sanitize_text("1º lugar e 3ª posição") == "primeiro lugar e terceira posição"


def test_sanitize_strips_shapes_and_symbols():
    # Formas geométricas soltas → nada falável.
    assert _sanitize_text("◆ ■ ● ▲ ○ ►") == ""
    # Formas no meio da frase são removidas, o texto continua legível.
    assert _sanitize_text("Capítulo ■ 1: A ● chegada") == "Capítulo um: A chegada"
    assert _sanitize_text("★★★ 5 estrelas") == "cinco estrelas"


def test_sanitize_strips_foreign_scripts():
    # Cirílico/CJK/árabe somem; a palavra latina permanece (nada de "viajar").
    assert _sanitize_text("Текст 中文 مرحبا café") == "café"


def test_sanitize_removes_urls_and_emails():
    assert _sanitize_text("veja em https://exemplo.com/x?y=1 agora") == "veja em agora"
    assert _sanitize_text("contato: a@b.com para falar") == "contato: para falar"


def test_sanitize_normalizes_punctuation():
    assert _sanitize_text("Ele disse “olá” — e sumiu…") == 'Ele disse "olá", e sumiu.'
    assert _sanitize_text("Bom dia!!! Tudo bem???") == "Bom dia! Tudo bem?"


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
