from __future__ import annotations

from pathlib import Path

from backend.pdf.extractor import extract_blocks
from backend.pdf.reflow import build_document

FIXTURES = Path(__file__).parent / "fixtures"


def _full_text(doc: dict) -> str:
    parts: list[str] = []
    for sec in doc["sections"]:
        if sec["title"]:
            parts.append(sec["title"])
        for p in sec["paragraphs"]:
            parts.append(p["text"])
    return "\n".join(parts)


def _build(pdf: Path) -> dict:
    blocks = extract_blocks(pdf)
    return build_document(blocks, str(pdf), pdf.name)


def test_artigo_academico_strips_urls_doi_isbn_copyright():
    doc = _build(FIXTURES / "artigo_academico.pdf")
    text = _full_text(doc).lower()
    assert "https://" not in text
    assert "doi:" not in text and "10.1234" not in text
    assert "isbn" not in text
    assert "todos os direitos reservados" not in text
    assert "editora sintética" not in text


def test_artigo_academico_drops_enumeration_refs():
    doc = _build(FIXTURES / "artigo_academico.pdf")
    text = _full_text(doc)
    # As referências [12] e [7] aparecem inline no parágrafo — não devem estar como blocos isolados,
    # mas o teste relevante é que NÃO há um bloco contendo só "[12]".
    for sec in doc["sections"]:
        for p in sec["paragraphs"]:
            assert p["text"].strip() not in ("[12]", "[7]")


def test_pdf_com_footer_pesado_remove_pagina_e_editora():
    doc = _build(FIXTURES / "pdf_com_footer_pesado.pdf")
    text = _full_text(doc).lower()
    assert "página 1" not in text
    assert "página 2" not in text
    assert "editora exemplo" not in text
    assert "todos os direitos reservados" not in text


def test_livro_simples_keeps_body():
    doc = _build(FIXTURES / "livro_simples.pdf")
    text = _full_text(doc)
    assert "leitor curioso" in text
    assert doc["metadata"]["pages"] >= 1


def test_metadata_has_removal_stats():
    doc = _build(FIXTURES / "artigo_academico.pdf")
    meta = doc["metadata"]
    assert meta["removed_chars"] > 0
    assert isinstance(meta["removal_reasons"], dict)
