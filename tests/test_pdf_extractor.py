from __future__ import annotations

from pathlib import Path

from backend.pdf.extractor import extract_blocks

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_blocks_returns_text():
    blocks = extract_blocks(FIXTURES / "livro_simples.pdf")
    assert len(blocks) > 0
    all_text = " ".join(b.text for b in blocks)
    assert "leitor curioso" in all_text


def test_extract_blocks_has_metadata():
    blocks = extract_blocks(FIXTURES / "livro_simples.pdf")
    sample = blocks[0]
    assert sample.bbox and len(sample.bbox) == 4
    assert sample.size > 0
    assert sample.page >= 0


def test_extract_blocks_columns():
    blocks = extract_blocks(FIXTURES / "pdf_com_colunas.pdf")
    assert len(blocks) > 0
