"""OCR opcional para PDFs escaneados (imagem, sem texto selecionável).

Só funciona se o binário do Tesseract (idioma português) e o pytesseract
estiverem instalados. Quando não estão, `ocr_available()` devolve False e o
chamador mostra uma mensagem amigável em vez de um livro vazio.
"""
from __future__ import annotations

import re
from pathlib import Path
from shutil import which

from backend.utils.logging import get_logger

logger = get_logger("pdf.ocr")


def ocr_available() -> bool:
    """True só se dá para OCR de verdade (pytesseract + binário do Tesseract)."""
    try:
        import pytesseract  # noqa: F401
    except Exception:
        return False
    return which("tesseract") is not None


def ocr_pdf_blocks(path: str | Path, dpi: int = 200, lang: str = "por") -> list[tuple[str, str]] | None:
    """Rasteriza cada página e reconhece o texto. Devolve blocos
    ("paragraph", texto) ou None se o OCR não estiver disponível/falhar."""
    if not ocr_available():
        return None
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        doc = fitz.open(str(path))
        blocks: list[tuple[str, str]] = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            txt = pytesseract.image_to_string(img, lang=lang)
            txt = re.sub(r"[ \t]+", " ", txt)
            for para in re.split(r"\n\s*\n", txt):
                para = re.sub(r"\s+", " ", para).strip()
                if len(para) >= 3:
                    blocks.append(("paragraph", para))
        return blocks or None
    except Exception:
        logger.exception("OCR falhou")
        return None
