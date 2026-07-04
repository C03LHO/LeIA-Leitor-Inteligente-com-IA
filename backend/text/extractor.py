"""Extração de TXT e DOCX para o mesmo schema de documento do PDF/EPUB.

Produz `{"metadata": {...}, "sections": [{id, level, title, paragraphs: [
{id, text, page, sentences: [{id, text}]}]}]}` — igual ao build_epub_document,
para o leitor e o cache de áudio funcionarem sem nada de especial.
"""
from __future__ import annotations

import re
from pathlib import Path

# Heurística de título: linha curta e isolada que começa com "Capítulo/Parte…"
# ou está toda em MAIÚSCULAS.
_HEADING_RE = re.compile(
    r"^\s*(cap[íi]tulo|parte|livro|se[çc][ãa]o|pr[óo]logo|ep[íi]logo|"
    r"introdu[çc][ãa]o|conclus[ãa]o|ap[êe]ndice)\b",
    re.IGNORECASE,
)


def build_document_from_blocks(
    blocks: list[tuple[str, str]],
    filename: str,
    author: str = "",
    pages: int = 1,
) -> dict:
    """Monta o documento a partir de uma lista de blocos ("heading"|"paragraph", texto)."""
    from backend.tts.streamer import merge_enumerators, split_sentences

    sections: list[dict] = [{"id": "sec_0", "level": 1, "title": "", "paragraphs": []}]
    current = sections[0]
    sec_n = 0
    para_n = 0

    for kind, text in blocks:
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            continue
        if kind == "heading":
            sec_n += 1
            current = {"id": f"sec_{sec_n}", "level": 1, "title": text, "paragraphs": []}
            sections.append(current)
        else:
            pid = f"p_{para_n}"
            para_n += 1
            parts = merge_enumerators(split_sentences(text))
            current["paragraphs"].append(
                {
                    "id": pid,
                    "text": text,
                    "page": 0,
                    "sentences": [
                        {"id": f"{pid}_s{i}", "text": t} for i, t in enumerate(parts) if t
                    ],
                }
            )

    sections = [s for s in sections if s["paragraphs"] or s["title"]]
    extracted = sum(len(p["text"]) for s in sections for p in s["paragraphs"]) + sum(
        len(s["title"]) for s in sections
    )
    return {
        "metadata": {
            "filename": filename,
            "author": author,
            "pages": pages,
            "extracted_chars": extracted,
            "removed_chars": 0,
            "removal_reasons": {},
        },
        "sections": sections,
    }


def _read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _looks_heading(chunk: str) -> bool:
    lines = [ln for ln in chunk.splitlines() if ln.strip()]
    if len(lines) != 1:
        return False
    line = lines[0].strip()
    if len(line) > 70:
        return False
    return bool(_HEADING_RE.match(line)) or (line.isupper() and len(line) >= 3)


def build_txt_document(path: str | Path, filename: str) -> dict:
    text = _read_text(path)
    blocks: list[tuple[str, str]] = []
    for chunk in re.split(r"\n\s*\n", text):  # parágrafos separados por linha em branco
        if not chunk.strip():
            continue
        kind = "heading" if _looks_heading(chunk) else "paragraph"
        blocks.append((kind, chunk))
    return build_document_from_blocks(blocks, filename, pages=1)


def build_docx_document(path: str | Path, filename: str) -> dict:
    import docx  # python-docx

    doc = docx.Document(str(path))
    try:
        author = (doc.core_properties.author or "").strip()
    except Exception:
        author = ""
    blocks: list[tuple[str, str]] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        style = ""
        try:
            style = (p.style.name or "").lower()
        except Exception:
            pass
        is_head = style.startswith("heading") or style.startswith("título") or style.startswith("titulo")
        blocks.append(("heading" if is_head else "paragraph", t))
    return build_document_from_blocks(blocks, filename, author=author, pages=1)
