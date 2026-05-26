"""Gera PDFs de fixture sintéticos para os testes de extração/limpeza.

Cobre os 4 cenários do plano:
  - livro_simples.pdf:        layout simples, 1 coluna, header/footer recorrentes
  - artigo_academico.pdf:     URLs, DOI, ISBN, copyright, citações [12], notas
  - pdf_com_colunas.pdf:      2 colunas
  - pdf_com_footer_pesado.pdf: rodapé extenso com editora e copyright em toda página
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PARA = (
    "Era uma vez um leitor curioso que descobriu uma forma de transformar "
    "qualquer documento em uma narração natural. A ideia parecia simples, "
    "mas exigia tratar cuidadosamente cada parte do texto."
)


def _write_page(c: canvas.Canvas, lines: list[tuple[str, float, float, str, float]]):
    for text, x, y, font, size in lines:
        c.setFont(font, size)
        c.drawString(x, y, text)


def make_livro_simples(path: Path, pages: int = 5) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    for p in range(pages):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(72, height - 36, "Livro de Exemplo — Capítulo 1")
        c.setFont("Helvetica", 9)
        c.drawCentredString(width / 2, 30, str(p + 1))

        if p == 0:
            c.setFont("Helvetica-Bold", 18)
            c.drawString(72, height - 120, "Introdução")

        c.setFont("Helvetica", 12)
        y = height - 160
        for _ in range(8):
            for line in _wrap(PARA, 80):
                c.drawString(72, y, line)
                y -= 16
            y -= 10
        c.showPage()
    c.save()


def make_artigo_academico(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 9)
    c.drawString(72, height - 36, "Revista de Estudos Sintéticos — Vol. 12 (2024)")
    c.setFont("Helvetica", 8)
    c.drawString(72, 40, "https://exemplo.org/artigo/123")
    c.drawString(72, 28, "DOI: 10.1234/exemplo.2024.001")
    c.drawString(72, 16, "ISBN: 978-3-16-148410-0")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 110, "Um Estudo Sintético")

    c.setFont("Helvetica", 11)
    y = height - 150
    for line in _wrap(
        PARA + " Esta passagem cita um autor anterior [12] e outro [7] que discutiram o tema.",
        85,
    ):
        c.drawString(72, y, line)
        y -= 14

    y -= 20
    c.setFont("Helvetica", 7)
    c.drawString(72, y, "1 Nota de rodapé com fonte minúscula, normalmente ignorada.")
    y -= 10
    c.drawString(72, y, "2 Outra nota de rodapé curta.")

    y -= 30
    c.setFont("Helvetica", 9)
    c.drawString(72, y, "© 2024 Editora Sintética. Todos os direitos reservados.")
    c.showPage()
    c.save()


def make_pdf_com_colunas(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica", 11)
    left_x, right_x = 60, width / 2 + 20
    col_width_chars = 45
    y_left = y_right = height - 80
    for _ in range(6):
        for line in _wrap(PARA, col_width_chars):
            c.drawString(left_x, y_left, line)
            y_left -= 14
        y_left -= 8
    for _ in range(6):
        for line in _wrap(PARA, col_width_chars):
            c.drawString(right_x, y_right, line)
            y_right -= 14
        y_right -= 8
    c.showPage()
    c.save()


def make_pdf_com_footer_pesado(path: Path, pages: int = 4) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    for p in range(pages):
        c.setFont("Helvetica", 12)
        y = height - 80
        for _ in range(6):
            for line in _wrap(PARA, 80):
                c.drawString(60, y, line)
                y -= 16
            y -= 8
        c.setFont("Helvetica", 8)
        c.drawString(60, 50, "Editora Exemplo — https://www.editora-exemplo.com")
        c.drawString(60, 38, "© 2024 Editora Exemplo. Todos os direitos reservados.")
        c.drawCentredString(width / 2, 24, f"Página {p + 1}")
        c.showPage()
    c.save()


def _wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        if len(current) + 1 + len(w) > max_chars:
            lines.append(current)
            current = w
        else:
            current = (current + " " + w).strip()
    if current:
        lines.append(current)
    return lines


def generate_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    make_livro_simples(out_dir / "livro_simples.pdf")
    make_artigo_academico(out_dir / "artigo_academico.pdf")
    make_pdf_com_colunas(out_dir / "pdf_com_colunas.pdf")
    make_pdf_com_footer_pesado(out_dir / "pdf_com_footer_pesado.pdf")


if __name__ == "__main__":
    here = Path(__file__).parent
    generate_all(here)
    print(f"Fixtures gerados em {here}")
