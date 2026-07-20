"""Sincroniza um áudio (audiolivro humano) com o TEXTO já conhecido do livro.

Estratégia: o Whisper (faster-whisper) transcreve o áudio com tempo por palavra;
depois casamos essa sequência de palavras com as palavras das FRASES do livro
(alinhamento de sequência) para descobrir o início/fim de cada frase no áudio.
Assim o leitor destaca a frase acompanhando a voz humana.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

from backend.utils.logging import get_logger

logger = get_logger("align.aligner")


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _norm(word: str) -> str:
    """Normaliza para comparar: sem acento, minúsculo, só letras/números."""
    w = unicodedata.normalize("NFD", word or "")
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w.lower())


def transcribe_words(audio_path: str | Path, model_size: str = "small", progress_cb=None) -> list[dict]:
    """Transcreve o áudio e devolve [{n, start, end}] por palavra (n = normalizada)."""
    from faster_whisper import WhisperModel
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    logger.info("Whisper %s em %s/%s", model_size, device, compute)
    model = WhisperModel(model_size, device=device, compute_type=compute)
    segments, info = model.transcribe(
        str(audio_path), language="pt", word_timestamps=True, vad_filter=True
    )
    total = float(getattr(info, "duration", 0) or 0)
    words: list[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            n = _norm(w.word)
            if n:
                words.append({"n": n, "start": float(w.start), "end": float(w.end)})
        if progress_cb and total:
            progress_cb(min(0.98, float(seg.end or 0) / total))
    return words


def align_sentences(sentences: list[dict], asr_words: list[dict]) -> list[dict]:
    """Casa as frases do livro com as palavras transcritas → [{id, start, end}].

    sentences: [{id, text}] na ordem do livro. asr_words: saída de transcribe_words.
    """
    # 1) palavras de referência (do livro), guardando a frase de cada uma
    ref: list[tuple[str, int]] = []
    for si, s in enumerate(sentences):
        for tok in re.findall(r"\S+", s.get("text", "")):
            n = _norm(tok)
            if n:
                ref.append((n, si))
    if not ref or not asr_words:
        return []

    ref_norm = [r[0] for r in ref]
    asr_norm = [w["n"] for w in asr_words]

    # 2) alinhamento de sequência ref <-> asr
    sm = difflib.SequenceMatcher(a=ref_norm, b=asr_norm, autojunk=False)
    ref_time: list[float | None] = [None] * len(ref)
    for a0, b0, size in sm.get_matching_blocks():
        for k in range(size):
            ref_time[a0 + k] = asr_words[b0 + k]["start"]

    # 3) preenche tempos faltantes (âncoras + interpolação linear + monotônico)
    anchors = [i for i, t in enumerate(ref_time) if t is not None]
    if not anchors:
        return []
    first, last = anchors[0], anchors[-1]
    for i in range(first):
        ref_time[i] = ref_time[first]
    for i in range(last + 1, len(ref_time)):
        ref_time[i] = ref_time[last]
    for a, b in zip(anchors, anchors[1:]):
        if b > a + 1:
            ta, tb = ref_time[a], ref_time[b]
            for k in range(a + 1, b):
                ref_time[k] = ta + (tb - ta) * (k - a) / (b - a)
    for i in range(1, len(ref_time)):
        if ref_time[i] < ref_time[i - 1]:
            ref_time[i] = ref_time[i - 1]

    # 4) início/fim por frase
    sent_start: dict[int, float] = {}
    sent_end: dict[int, float] = {}
    for i, (_, si) in enumerate(ref):
        t = float(ref_time[i])
        sent_start.setdefault(si, t)
        sent_end[si] = t

    audio_end = float(asr_words[-1]["end"])
    out: list[dict] = []
    for si, s in enumerate(sentences):
        start = sent_start.get(si)
        if start is None:  # frase sem palavras casadas → cola no anterior
            start = out[-1]["end"] if out else 0.0
            end = start
        else:
            end = max(sent_end.get(si, start), start)
        out.append({"id": s["id"], "start": round(start, 3), "end": round(end, 3)})

    # 5) fim de cada frase = início da próxima (destaque contínuo); último = fim do áudio
    for i in range(len(out) - 1):
        nxt = out[i + 1]["start"]
        if nxt > out[i]["end"]:
            out[i]["end"] = nxt
    if out:
        out[-1]["end"] = max(out[-1]["end"], audio_end)
    return out
