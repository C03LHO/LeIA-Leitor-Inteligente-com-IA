"""Normalização de texto para narração em pt-BR.

Converte para fala o que o XTTS leria mal ou "por extenso errado": números
(1234 -> "mil duzentos e trinta e quatro"), moeda (R$ 45,90 -> "quarenta e
cinco reais e noventa centavos"), porcentagem, ordinais (1º -> "primeiro"),
numerais romanos em contexto (século XIX -> "século dezenove", Dom Pedro II ->
"Dom Pedro segundo"), horas (14h30 -> "quatorze horas e trinta") e abreviações
comuns (Dr. -> "Doutor", pág. -> "página", nº -> "número").

Roda ANTES do descarte de símbolos em _sanitize_text, então ainda enxerga
"R$", "%", "º" e "ª" para interpretá-los.
"""
from __future__ import annotations

import re

try:
    from num2words import num2words as _n2w

    _HAS_N2W = True
except Exception:  # pragma: no cover - num2words é dependência garantida
    _HAS_N2W = False


def _card(n: int) -> str:
    """Cardinal por extenso, sem as vírgulas que o num2words insere (viram
    pausa estranha na fala)."""
    if not _HAS_N2W:
        return str(n)
    try:
        return _n2w(n, lang="pt_BR").replace(",", "")
    except Exception:
        return str(n)


def _ord(n: int, feminine: bool = False) -> str:
    if not _HAS_N2W:
        return str(n)
    try:
        w = _n2w(n, lang="pt_BR", to="ordinal").replace(",", "")
    except Exception:
        return str(n)
    if feminine:
        # "primeiro" -> "primeira", "vigésimo segundo" -> "vigésima segunda"
        w = re.sub(r"o\b", "a", w)
    return w


# ------------------------------------------------------------------ romanos
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_to_int(s: str) -> int | None:
    s = s.upper()
    if not s or any(ch not in _ROMAN for ch in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN[ch]
        total += -val if val < prev else val
        prev = max(prev, val)
    # valida (evita "IIII", "VV" etc. serem aceitos como número)
    if total <= 0 or total > 3999:
        return None
    return total


# Gatilhos que garantem que a sequência de letras é MESMO um romano (não
# iniciais/algarismo solto). Século/capítulo -> cardinal; monarca -> ordinal
# até dez, cardinal acima (convenção do português: "Pedro segundo", "Luís
# catorze", "João vinte e três").
_CENTURY_TRIGGERS = r"s[ée]culo|cap[íi]tulo|cap|tomo|volume|livro|parte|canto|ato|artigo|art"
_MONARCH_TRIGGERS = (
    r"rei|rainha|papa|dom|dona|imperador|imperatriz|"
    r"lu[íi]s|luiz|pedro|jo[ãa]o|henrique|carlos|felipe|filipe|afonso|fernando|"
    r"benedito|bento|francisco|le[ãa]o|pio|greg[óo]rio|clemente|urbano"
)
_RE_ROMAN_CENTURY = re.compile(
    rf"\b({_CENTURY_TRIGGERS})(\s+)([IVXLCDM]{{1,7}})\b", re.IGNORECASE
)
_RE_ROMAN_MONARCH = re.compile(
    rf"\b({_MONARCH_TRIGGERS})(\s+)([IVXLCDM]{{1,7}})\b", re.IGNORECASE
)


def _sub_roman_century(m: re.Match) -> str:
    n = _roman_to_int(m.group(3))
    if n is None:
        return m.group(0)
    return f"{m.group(1)}{m.group(2)}{_card(n)}"


def _sub_roman_monarch(m: re.Match) -> str:
    n = _roman_to_int(m.group(3))
    if n is None:
        return m.group(0)
    word = _ord(n) if n <= 10 else _card(n)
    return f"{m.group(1)}{m.group(2)}{word}"


# ------------------------------------------------------------------ moeda
_RE_CURRENCY = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?")


def _sub_currency(m: re.Match) -> str:
    reais = int(m.group(1).replace(".", ""))
    cents = int((m.group(2) or "0").ljust(2, "0")[:2])
    parts = []
    parts.append("um real" if reais == 1 else f"{_card(reais)} reais")
    if cents:
        parts.append("um centavo" if cents == 1 else f"{_card(cents)} centavos")
    return " e ".join(parts)


# ------------------------------------------------------------------ número puro
def _num_str_to_words(num: str) -> str:
    """'1.234' -> palavras; '3,14' -> 'três vírgula um quatro'."""
    if "," in num:
        inteiro, frac = num.split(",", 1)
        inteiro = inteiro.replace(".", "") or "0"
        head = _card(int(inteiro))
        tail = " ".join(_card(int(d)) for d in frac)
        return f"{head} vírgula {tail}"
    digits = num.replace(".", "")
    if len(digits) > 15:  # num2words estoura em números gigantes
        return num
    return _card(int(digits))


_RE_PERCENT = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s?%")
_RE_TIME = re.compile(r"\b(\d{1,2})h(\d{2})?\b")
# Não trata como ordinal quando é temperatura (30°C, 98°F) — aí o "°" vira
# "graus" no mapa de caracteres.
_RE_ORDINAL = re.compile(r"\b(\d+)\s?([º°ª])(?![CFKcfk])")
_RE_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")


def _sub_percent(m: re.Match) -> str:
    return f"{_num_str_to_words(m.group(1))} por cento"


def _sub_time(m: re.Match) -> str:
    h = int(m.group(1))
    hora = "uma hora" if h == 1 else f"{_card(h)} horas"
    if m.group(2):
        mins = int(m.group(2))
        if mins:
            return f"{hora} e {_card(mins)}"
    return hora


def _sub_ordinal(m: re.Match) -> str:
    return _ord(int(m.group(1)), feminine=m.group(2) == "ª")


# ------------------------------------------------------------------ abreviações
# (padrão, substituição) — mais específicas/longas primeiro. Case-insensitive.
_ABBREV: list[tuple[str, str]] = [
    (r"\bDra\.", "Doutora"), (r"\bDr\.", "Doutor"),
    (r"\bSra\.", "Senhora"), (r"\bSrta\.", "Senhorita"), (r"\bSr\.", "Senhor"),
    (r"\bProfa\.", "Professora"), (r"\bProf\.", "Professor"),
    (r"\bp[áa]gs\.", "páginas"), (r"\bp[áa]g\.", "página"),
    (r"\bs[ée]culos\b", "séculos"), (r"\bs[ée]c\.", "século"),
    (r"\bcap[íi]tulos\b", "capítulos"), (r"\bcaps\.", "capítulos"), (r"\bcap\.", "capítulo"),
    (r"\barts\.", "artigos"), (r"\bart\.", "artigo"),
    (r"\bn[º°]", "número"), (r"\bn\.[º°]", "número"),
    (r"\bvol\.", "volume"), (r"\bed\.", "edição"),
    (r"\bpp\.", "páginas"),
    (r"\betc\.", "etcétera"),
    (r"\bp\.\s?ex\.", "por exemplo"), (r"\bex\.:", "exemplo:"),
    (r"\bvs\.", "versus"),
    (r"§", " parágrafo "), (r"&", " e "),
]
_ABBREV_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in _ABBREV]


def normalize(text: str) -> str:
    """Aplica todas as expansões, na ordem correta (específicas antes das
    genéricas)."""
    if not text:
        return text
    t = text
    for rx, repl in _ABBREV_COMPILED:
        t = rx.sub(repl, t)
    t = _RE_ROMAN_CENTURY.sub(_sub_roman_century, t)
    t = _RE_ROMAN_MONARCH.sub(_sub_roman_monarch, t)
    t = _RE_CURRENCY.sub(_sub_currency, t)
    t = _RE_PERCENT.sub(_sub_percent, t)
    t = _RE_TIME.sub(_sub_time, t)
    t = _RE_ORDINAL.sub(_sub_ordinal, t)
    t = _RE_NUMBER.sub(lambda m: _num_str_to_words(m.group(0)), t)
    return t
