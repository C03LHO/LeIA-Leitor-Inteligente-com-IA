from __future__ import annotations

import re
from dataclasses import dataclass, field

import pyphen

from backend.pdf.cleaner import (
    CleaningConfig,
    CleaningStats,
    body_font_size,
    classify_block,
    detect_recurring_headers_footers,
    strip_inline_urls,
)
from backend.pdf.extractor import RawBlock, page_dimensions

_HYPHENATOR = pyphen.Pyphen(lang="pt_BR")
_SENT_END = (".", "!", "?", ":", ";", "…", '"', "”", "’", ")")


@dataclass
class Paragraph:
    id: str
    text: str
    page: int
    sentences: list = field(default_factory=list)


@dataclass
class Section:
    id: str
    level: int
    title: str
    paragraphs: list[Paragraph]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "paragraphs": [
                {"id": p.id, "text": p.text, "page": p.page, "sentences": p.sentences}
                for p in self.paragraphs
            ],
        }


def _is_real_hyphenated_word(left: str, right: str) -> bool:
    """Heuristic: if pyphen would naturally hyphenate `leftright` at this point,
    treat the hyphen as a line-break artifact; otherwise it's a real compound."""
    candidate = f"{left}{right}"
    if not candidate.isalpha():
        return True
    hyphenated = _HYPHENATOR.inserted(candidate)
    return f"{left}-{right}" in hyphenated


def _merge_hyphen_break(prev: str, nxt: str) -> str:
    if not prev.endswith("-"):
        return prev + " " + nxt
    if not nxt or not nxt[0].islower():
        return prev[:-1] + nxt
    left = re.split(r"\s+", prev)[-1].rstrip("-")
    right = re.split(r"\s+", nxt, maxsplit=1)[0]
    if not left or not right:
        return prev[:-1] + nxt
    if _is_real_hyphenated_word(left, right):
        return prev + nxt
    return prev[:-1] + nxt


_EDGE_MARKERS = set('"\'`&*†‡§¶()[]{}<>|~^_+=\\/')


def _strip_edge_markers(text: str) -> str:
    """Remove ruído de marcadores de nota/figura nas pontas (ex.: títulos que vêm
    com âncoras de rodapé grudadas: 'As Nove Situações (*', 'Variação de Táticas &')."""
    out = text.strip()
    while out and out[-1] in _EDGE_MARKERS:
        out = out[:-1].rstrip()
    while out and out[0] in _EDGE_MARKERS:
        out = out[1:].lstrip()
    return out or text.strip()


def _join_block_lines(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    out = lines[0]
    for line in lines[1:]:
        if out.endswith("-"):
            out = _merge_hyphen_break(out, line)
        elif out.endswith(_SENT_END):
            out = out + " " + line
        else:
            out = out + " " + line
    return re.sub(r"\s{2,}", " ", out).strip()


def _sort_blocks_reading_order(
    blocks: list[RawBlock], page_widths: dict[int, float]
) -> list[RawBlock]:
    by_page: dict[int, list[RawBlock]] = {}
    for b in blocks:
        by_page.setdefault(b.page, []).append(b)

    ordered: list[RawBlock] = []
    for page in sorted(by_page.keys()):
        page_blocks = by_page[page]
        width = page_widths.get(page, 0)
        if width <= 0:
            ordered.extend(sorted(page_blocks, key=lambda b: (b.bbox[1], b.bbox[0])))
            continue

        midline = width / 2
        left_col = [b for b in page_blocks if b.bbox[2] <= midline + width * 0.05]
        right_col = [b for b in page_blocks if b.bbox[0] >= midline - width * 0.05]
        used = set(id(b) for b in left_col) | set(id(b) for b in right_col)
        rest = [b for b in page_blocks if id(b) not in used]

        if len(left_col) >= 3 and len(right_col) >= 3 and not rest:
            ordered.extend(sorted(left_col, key=lambda b: (b.bbox[1], b.bbox[0])))
            ordered.extend(sorted(right_col, key=lambda b: (b.bbox[1], b.bbox[0])))
        else:
            ordered.extend(sorted(page_blocks, key=lambda b: (b.bbox[1], b.bbox[0])))
    return ordered


def _should_merge_with_previous(prev_text: str, current_text: str) -> bool:
    if not prev_text:
        return False
    last = prev_text.rstrip()
    if not last:
        return False
    if last[-1] in _SENT_END:
        return False
    if current_text and current_text[0].isupper() and last[-1] not in (",", "-"):
        return False
    return True


def build_sections(
    blocks: list[RawBlock],
    pdf_path: str,
    cfg: CleaningConfig | None = None,
) -> tuple[list[Section], CleaningStats]:
    cfg = cfg or CleaningConfig()
    stats = CleaningStats()

    dims = page_dimensions(pdf_path)
    page_widths = {i: w for i, (w, _) in enumerate(dims)}
    page_heights = {i: h for i, (_, h) in enumerate(dims)}

    body_size = body_font_size(blocks)
    flagged_hf = detect_recurring_headers_footers(blocks, page_heights, cfg)
    ordered = _sort_blocks_reading_order(blocks, page_widths)

    sections: list[Section] = []
    current = Section(id="sec_0", level=1, title="", paragraphs=[])
    sections.append(current)
    para_counter = 0
    sec_counter = 0

    last_paragraph: Paragraph | None = None

    for block in ordered:
        kind, reason = classify_block(
            block, body_size, cfg, flagged_hf, page_heights.get(block.page, 0)
        )
        joined = _join_block_lines(block.text)
        char_len = len(joined)

        if kind == "drop":
            stats.record_removal(reason or "other", char_len)
            continue

        if cfg.strip_inline_urls:
            joined = strip_inline_urls(joined)
            if not joined:
                stats.record_removal("urls", char_len)
                continue

        if kind == "heading":
            sec_counter += 1
            current = Section(
                id=f"sec_{sec_counter}",
                level=1,
                title=_strip_edge_markers(joined),
                paragraphs=[],
            )
            sections.append(current)
            last_paragraph = None
            stats.record_keep(len(joined))
            continue

        if last_paragraph and last_paragraph.page == block.page and _should_merge_with_previous(
            last_paragraph.text, joined
        ):
            if last_paragraph.text.endswith("-"):
                last_paragraph.text = _merge_hyphen_break(last_paragraph.text, joined)
            else:
                last_paragraph.text = (last_paragraph.text + " " + joined).strip()
            stats.record_keep(len(joined))
            continue

        para = Paragraph(id=f"p_{para_counter}", text=joined, page=block.page)
        para_counter += 1
        current.paragraphs.append(para)
        last_paragraph = para
        stats.record_keep(len(joined))

    sections = [s for s in sections if s.paragraphs or s.title]
    return sections, stats


def build_document(
    blocks: list[RawBlock], pdf_path: str, filename: str, cfg: CleaningConfig | None = None
) -> dict:
    sections, stats = build_sections(blocks, pdf_path, cfg)

    # Divisão de frases no backend → ids estáveis no JSON. O frontend renderiza a
    # partir disso e a pré-geração de áudio usa exatamente as mesmas frases (cache casa).
    from backend.tts.streamer import merge_enumerators, split_sentences

    for sec in sections:
        for p in sec.paragraphs:
            parts = merge_enumerators(split_sentences(p.text))
            p.sentences = [
                {"id": f"{p.id}_s{i}", "text": t} for i, t in enumerate(parts) if t
            ]

    total_pages = (max((b.page for b in blocks), default=-1) + 1)
    extracted_chars = sum(len(p.text) for s in sections for p in s.paragraphs) + sum(
        len(s.title) for s in sections
    )
    return {
        "metadata": {
            "filename": filename,
            "pages": total_pages,
            "extracted_chars": extracted_chars,
            "removed_chars": stats.removed_chars,
            "removal_reasons": stats.as_dict()["removal_reasons"],
        },
        "sections": [s.to_dict() for s in sections],
    }
