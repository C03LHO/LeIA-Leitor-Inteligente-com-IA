from __future__ import annotations

import io
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
DC_NS = "http://purl.org/dc/elements/1.1/"

BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}
HEADING_TAGS = {"h1", "h2", "h3"}
SKIP_TAGS = {"script", "style", "head", "title"}


class _HTMLBlocks(HTMLParser):
    """Extrai blocos (heading | paragraph) do XHTML de um capítulo EPUB."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._skip = 0
        self._heading = False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag in BLOCK_TAGS:
            self._flush()
            self._heading = tag in HEADING_TAGS
        elif tag == "br":
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            self.blocks.append(("heading" if self._heading else "paragraph", text))
        self._heading = False


def _opf_path(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = root.find(f".//{{{CONTAINER_NS}}}rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB inválido: container.xml sem rootfile")
    return rootfile.get("full-path")


def _parse_opf(zf: zipfile.ZipFile):
    opf_path = _opf_path(zf)
    opf = ET.fromstring(zf.read(opf_path))
    manifest: dict[str, dict] = {}
    for item in opf.iter(f"{{{OPF_NS}}}item"):
        manifest[item.get("id")] = {
            "href": item.get("href"),
            "media_type": item.get("media-type") or "",
            "properties": item.get("properties") or "",
        }
    spine = [it.get("idref") for it in opf.iter(f"{{{OPF_NS}}}itemref")]
    cover_meta_id = None
    for meta in opf.iter(f"{{{OPF_NS}}}meta"):
        if meta.get("name") == "cover":
            cover_meta_id = meta.get("content")
    creator = opf.find(f".//{{{DC_NS}}}creator")
    author = (creator.text or "").strip() if creator is not None and creator.text else ""
    base = posixpath.dirname(opf_path)
    return manifest, spine, base, cover_meta_id, author


def build_epub_document(epub_path: str | Path, filename: str) -> dict:
    from backend.tts.streamer import merge_enumerators, split_sentences

    try:
        zf = zipfile.ZipFile(epub_path)
    except Exception as exc:
        raise ValueError("Não foi possível abrir o EPUB — pode estar corrompido.") from exc

    with zf:
        manifest, spine, base, _, author = _parse_opf(zf)

        sections: list[dict] = [{"id": "sec_0", "level": 1, "title": "", "paragraphs": []}]
        current = sections[0]
        sec_n = 0
        para_n = 0

        for sid in spine:
            item = manifest.get(sid)
            if not item or "html" not in item["media_type"]:
                continue
            path = posixpath.normpath(posixpath.join(base, item["href"]))
            try:
                raw = zf.read(path).decode("utf-8", "replace")
            except KeyError:
                continue
            parser = _HTMLBlocks()
            try:
                parser.feed(raw)
            except Exception:
                continue
            for kind, text in parser.blocks:
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
            "pages": len(spine),
            "extracted_chars": extracted,
            "removed_chars": 0,
            "removal_reasons": {},
        },
        "sections": sections,
    }


def extract_epub_cover(epub_path: str | Path, out_path: str | Path, width: int = 420) -> bool:
    """Acha a capa embutida no EPUB e salva normalizada como PNG."""
    try:
        zf = zipfile.ZipFile(epub_path)
    except Exception:
        return False
    with zf:
        manifest, _, base, cover_meta_id, _ = _parse_opf(zf)
        href = None
        # 1) item com properties="cover-image"
        for item in manifest.values():
            if "cover-image" in item["properties"]:
                href = item["href"]
                break
        # 2) <meta name="cover" content="id">
        if not href and cover_meta_id and cover_meta_id in manifest:
            href = manifest[cover_meta_id]["href"]
        # 3) qualquer imagem com "cover" no href
        if not href:
            for item in manifest.values():
                if item["media_type"].startswith("image/") and "cover" in (item["href"] or "").lower():
                    href = item["href"]
                    break
        if not href:
            return False
        path = posixpath.normpath(posixpath.join(base, href))
        try:
            data = zf.read(path)
        except KeyError:
            return False

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        if img.width > width:
            h = int(img.height * (width / img.width))
            img = img.resize((width, h))
        img.save(str(out_path), "PNG")
        return True
    except Exception:
        return False
