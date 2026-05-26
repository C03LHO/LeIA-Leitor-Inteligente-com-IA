from __future__ import annotations

from pathlib import Path

from backend.pdf.extractor import extract_blocks
from backend.pdf.reflow import build_document
from backend.tts.streamer import split_sentences

FIXTURES = Path(__file__).parent / "fixtures"


def test_paragraphs_have_sentences_joined():
    blocks = extract_blocks(FIXTURES / "livro_simples.pdf")
    doc = build_document(blocks, str(FIXTURES / "livro_simples.pdf"), "livro_simples.pdf")
    for sec in doc["sections"]:
        for p in sec["paragraphs"]:
            assert "\n" not in p["text"]
            assert "  " not in p["text"]


def test_sentence_split_basic():
    text = "Olá mundo. Esta é a segunda frase! E a terceira?"
    out = split_sentences(text)
    assert len(out) == 3
    assert out[0].startswith("Olá")
    assert out[-1].endswith("?")
