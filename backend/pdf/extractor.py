from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF


@dataclass
class Span:
    text: str
    font: str
    size: float
    flags: int
    bbox: tuple[float, float, float, float]


@dataclass
class RawBlock:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    font: str
    size: float
    flags: int
    spans: list[Span] = field(default_factory=list)
    rotation: int = 0

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & 16)

    @property
    def is_italic(self) -> bool:
        return bool(self.flags & 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_bold"] = self.is_bold
        d["is_italic"] = self.is_italic
        return d


def _dominant_span(spans: list[dict]) -> tuple[str, float, int]:
    if not spans:
        return ("", 0.0, 0)
    biggest = max(spans, key=lambda s: len(s.get("text", "")))
    return (biggest.get("font", ""), float(biggest.get("size", 0)), int(biggest.get("flags", 0)))


def extract_blocks(pdf_path: str | Path) -> list[RawBlock]:
    """Extract structured blocks from a PDF using PyMuPDF.

    Returns a flat list of RawBlock; downstream stages handle cleaning,
    reflow and column detection.
    """
    blocks: list[RawBlock] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError("Não foi possível abrir o PDF — ele pode estar corrompido.") from exc
    with doc:
        if doc.needs_pass:
            raise ValueError("PDF protegido por senha. Remova a proteção e tente novamente.")
        for page_index, page in enumerate(doc):
            page_dict = page.get_text("dict")
            rotation = page.rotation
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                spans_flat: list[dict] = []
                line_texts: list[str] = []
                spans_objects: list[Span] = []
                for line in lines:
                    line_pieces: list[str] = []
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not text:
                            continue
                        line_pieces.append(text)
                        spans_flat.append(span)
                        spans_objects.append(
                            Span(
                                text=text,
                                font=span.get("font", ""),
                                size=float(span.get("size", 0)),
                                flags=int(span.get("flags", 0)),
                                bbox=tuple(span.get("bbox", block.get("bbox", (0, 0, 0, 0)))),
                            )
                        )
                    if line_pieces:
                        line_texts.append("".join(line_pieces))
                text = "\n".join(line_texts).strip()
                if not text:
                    continue
                font, size, flags = _dominant_span(spans_flat)
                bbox = tuple(block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                blocks.append(
                    RawBlock(
                        page=page_index,
                        bbox=bbox,
                        text=text,
                        font=font,
                        size=size,
                        flags=flags,
                        spans=spans_objects,
                        rotation=rotation,
                    )
                )
    return blocks


def render_cover(pdf_path: str | Path, out_path: str | Path, width: int = 420) -> bool:
    """Renderiza a 1ª página do PDF como PNG (capa do livro na estante)."""
    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            return False
        page = doc[0]
        page_w = page.rect.width or width
        zoom = max(0.1, width / page_w)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pix.save(str(out_path))
        return True


def page_dimensions(pdf_path: str | Path) -> list[tuple[float, float]]:
    dims: list[tuple[float, float]] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            r = page.rect
            dims.append((r.width, r.height))
    return dims


def blocks_as_jsonable(blocks: Iterable[RawBlock]) -> list[dict]:
    return [b.to_dict() for b in blocks]
