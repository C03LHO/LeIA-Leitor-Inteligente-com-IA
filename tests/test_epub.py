from __future__ import annotations

import io
import zipfile

from backend.epub.extractor import build_epub_document, extract_epub_cover


def _make_epub(path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 80), (20, 30, 40)).save(buf, "PNG")
    cover = buf.getvalue()

    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    opf = (
        '<?xml version="1.0"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Teste</dc:title>'
        '<meta name="cover" content="cover-img"/></metadata>'
        "<manifest>"
        '<item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>'
        '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
        "</manifest><spine><itemref idref=\"ch1\"/></spine></package>"
    )
    ch1 = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        "<h1>Capítulo Um</h1>"
        "<p>Era uma vez um leitor. Ele gostava de ouvir livros. Que coisa boa!</p>"
        "</body></html>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/ch1.xhtml", ch1)
        z.writestr("OEBPS/cover.png", cover)


def test_epub_extracts_sections_and_sentences(tmp_path):
    epub = tmp_path / "book.epub"
    _make_epub(epub)
    doc = build_epub_document(str(epub), "book.epub")
    titles = [s["title"] for s in doc["sections"]]
    assert "Capítulo Um" in titles
    sents = [s for sec in doc["sections"] for p in sec["paragraphs"] for s in p["sentences"]]
    assert len(sents) >= 2
    assert any("leitor" in s["text"] for s in sents)


def test_epub_cover(tmp_path):
    epub = tmp_path / "book.epub"
    _make_epub(epub)
    out = tmp_path / "cover.png"
    assert extract_epub_cover(str(epub), out) is True
    assert out.exists() and out.stat().st_size > 0
