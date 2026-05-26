from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from backend.pdf.extractor import RawBlock

URL_RE = re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.IGNORECASE)
URL_INLINE_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
DOI_RE = re.compile(r"^\s*(doi\s*:?|https?://(dx\.)?doi\.org/)\S+", re.IGNORECASE)
ISBN_RE = re.compile(r"\bISBN[\s:\-]*[0-9Xx\-]{9,}", re.IGNORECASE)
COPYRIGHT_RE = re.compile(
    r"(©|\(c\)\s*\d{4}|todos os direitos reservados|all rights reserved|copyright\s*\d{4})",
    re.IGNORECASE,
)
PUBLISHER_RE = re.compile(
    r"\b(editora|publisher|press|publishing|imprenta|edições?|publicações?)\b",
    re.IGNORECASE,
)
PAGE_NUMBER_RES = [
    re.compile(r"^\s*\d{1,4}\s*$"),
    re.compile(r"^\s*p[áa]gina\s+\d+(\s*/\s*\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
    re.compile(r"^\s*-\s*\d+\s*-\s*$"),
]
FIGURE_CAPTION_RE = re.compile(
    r"^\s*(figura|figure|tabela|table|fig\.|tab\.)\s*\d+", re.IGNORECASE
)
FOOTNOTE_MARKER_RE = re.compile(r"^\s*[¹²³⁴⁵⁶⁷⁸⁹⁰\*†‡§¶]+\s*$")
ENUM_REF_RE = re.compile(r"^\s*\[\d+\]\s*$")


@dataclass
class CleaningConfig:
    remove_headers_footers: bool = True
    remove_page_numbers: bool = True
    remove_urls: bool = True
    remove_dois: bool = True
    remove_isbn: bool = True
    remove_copyright: bool = True
    remove_publisher_lines: bool = True
    remove_footnotes: bool = True
    remove_figure_captions: bool = True
    remove_watermarks: bool = True
    strip_inline_urls: bool = True
    header_footer_top_ratio: float = 0.10
    header_footer_bottom_ratio: float = 0.90
    header_footer_min_freq: float = 0.30
    publisher_max_chars: int = 80
    footnote_size_ratio: float = 0.80


@dataclass
class CleaningStats:
    removed_chars: int = 0
    kept_chars: int = 0
    removal_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_removal(self, reason: str, chars: int) -> None:
        self.removed_chars += chars
        self.removal_reasons[reason] += chars

    def record_keep(self, chars: int) -> None:
        self.kept_chars += chars

    def as_dict(self) -> dict:
        return {
            "removed_chars": self.removed_chars,
            "kept_chars": self.kept_chars,
            "removal_reasons": dict(self.removal_reasons),
        }


def body_font_size(blocks: list[RawBlock]) -> float:
    sizes = [round(b.size, 1) for b in blocks if b.size > 0 and len(b.text) >= 20]
    if not sizes:
        sizes = [round(b.size, 1) for b in blocks if b.size > 0]
    if not sizes:
        return 12.0
    try:
        return float(statistics.mode(sizes))
    except statistics.StatisticsError:
        return float(statistics.median(sizes))


def _norm_for_freq(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def detect_recurring_headers_footers(
    blocks: list[RawBlock],
    page_heights: dict[int, float],
    cfg: CleaningConfig,
) -> set[tuple[int, str]]:
    """Identify (page, normalized_text) tuples that look like recurring headers/footers.

    A block is flagged if its normalized text appears in the top/bottom band of
    at least header_footer_min_freq fraction of pages.
    """
    pages = {b.page for b in blocks}
    if not pages:
        return set()
    n_pages = len(pages)

    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()
    block_band: dict[int, str] = {}

    for idx, b in enumerate(blocks):
        h = page_heights.get(b.page, 0)
        if h <= 0:
            continue
        y0, y1 = b.bbox[1], b.bbox[3]
        if y1 <= h * cfg.header_footer_top_ratio:
            band = "top"
        elif y0 >= h * cfg.header_footer_bottom_ratio:
            band = "bottom"
        else:
            continue
        norm = _norm_for_freq(b.text)
        if not norm:
            continue
        block_band[idx] = band
        if band == "top":
            top_counter[norm] += 1
        else:
            bottom_counter[norm] += 1

    threshold = max(2, int(n_pages * cfg.header_footer_min_freq))
    recurring_top = {t for t, c in top_counter.items() if c >= threshold}
    recurring_bottom = {t for t, c in bottom_counter.items() if c >= threshold}

    flagged: set[tuple[int, str]] = set()
    for idx, b in enumerate(blocks):
        band = block_band.get(idx)
        if not band:
            continue
        norm = _norm_for_freq(b.text)
        if band == "top" and norm in recurring_top:
            flagged.add((b.page, norm))
        elif band == "bottom" and norm in recurring_bottom:
            flagged.add((b.page, norm))
    return flagged


def _is_page_number(text: str) -> bool:
    return any(rgx.match(text) for rgx in PAGE_NUMBER_RES)


def classify_block(
    block: RawBlock,
    body_size: float,
    cfg: CleaningConfig,
    flagged_hf: set[tuple[int, str]],
    page_height: float,
) -> tuple[str, str]:
    """Return (kind, reason).

    kind ∈ {"heading", "paragraph", "drop"}.
    """
    text = block.text.strip()
    if not text:
        return ("drop", "empty")

    norm = _norm_for_freq(text)
    if cfg.remove_headers_footers and (block.page, norm) in flagged_hf:
        return ("drop", "headers_footers")

    if cfg.remove_page_numbers and _is_page_number(text):
        return ("drop", "page_numbers")

    if cfg.remove_watermarks and block.rotation not in (0, 360):
        return ("drop", "watermarks")

    if cfg.remove_footnotes and FOOTNOTE_MARKER_RE.match(text):
        return ("drop", "footnotes")

    if cfg.remove_footnotes and ENUM_REF_RE.match(text):
        return ("drop", "footnotes")

    if cfg.remove_urls and URL_RE.match(text):
        return ("drop", "urls")

    if cfg.remove_dois and DOI_RE.match(text):
        return ("drop", "urls")

    if cfg.remove_isbn and ISBN_RE.search(text):
        return ("drop", "isbn")

    if cfg.remove_copyright and COPYRIGHT_RE.search(text):
        return ("drop", "copyright")

    if (
        cfg.remove_publisher_lines
        and len(text) <= cfg.publisher_max_chars
        and PUBLISHER_RE.search(text)
    ):
        return ("drop", "publisher")

    if cfg.remove_figure_captions and FIGURE_CAPTION_RE.match(text) and len(text) < 200:
        return ("drop", "figure_captions")

    if (
        cfg.remove_footnotes
        and body_size > 0
        and block.size > 0
        and block.size < body_size * cfg.footnote_size_ratio
        and len(text) < 400
    ):
        return ("drop", "footnotes")

    if body_size > 0 and block.size >= body_size * 1.3 and len(text) < 200:
        return ("heading", "")

    return ("paragraph", "")


def strip_inline_urls(text: str) -> str:
    cleaned = URL_INLINE_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()
