from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def generate_fixtures():
    if all(
        (FIXTURES_DIR / name).exists()
        for name in (
            "livro_simples.pdf",
            "artigo_academico.pdf",
            "pdf_com_colunas.pdf",
            "pdf_com_footer_pesado.pdf",
        )
    ):
        return
    from tests.fixtures._generate import generate_all

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    generate_all(FIXTURES_DIR)
