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

import numpy as np

from backend.utils.logging import get_logger

logger = get_logger("align.aligner")

# Só uma sequência de >=N palavras iguais vira "âncora" de tempo. Isso evita
# casar palavrinhas comuns ("o", "a", "de", "que") no lugar errado, que era o
# que fazia o destaque não bater com o áudio.
_MIN_ANCHOR = 3


class AlignmentCancelled(Exception):
    """Sinaliza que a sincronização foi cancelada pelo usuário."""


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


def transcribe_words(audio_path: str | Path, model_size: str = "small", progress_cb=None, cancel_cb=None) -> list[dict]:
    """Transcreve o áudio e devolve [{n, start, end}] por palavra (n = normalizada).
    cancel_cb(): se devolver True entre segmentos, aborta com AlignmentCancelled."""
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
        if cancel_cb and cancel_cb():
            raise AlignmentCancelled()
        for w in (seg.words or []):
            n = _norm(w.word)
            if n:
                words.append({"n": n, "start": float(w.start), "end": float(w.end)})
        if progress_cb and total:
            progress_cb(min(0.98, float(seg.end or 0) / total))
    return words


def align_sentences(sentences: list[dict], asr_words: list[dict]) -> tuple[list[dict], float]:
    """Casa as frases do livro com as palavras transcritas.

    Devolve (lista [{id, start, end}], confiança 0..1). A confiança é a fração de
    palavras do livro cobertas por âncoras FORTES — baixa = o áudio provavelmente
    não bate com o texto (edição diferente, muito ruído/OCR, etc.).
    """
    # 1) palavras de referência (do livro), guardando a frase de cada uma
    ref: list[tuple[str, int]] = []
    for si, s in enumerate(sentences):
        for tok in re.findall(r"\S+", s.get("text", "")):
            n = _norm(tok)
            if n:
                ref.append((n, si))
    n_ref = len(ref)
    if not ref or not asr_words:
        return [], 0.0

    ref_norm = [r[0] for r in ref]
    asr_norm = [w["n"] for w in asr_words]
    sm = difflib.SequenceMatcher(a=ref_norm, b=asr_norm, autojunk=False)

    # 2) âncoras: só blocos de >=_MIN_ANCHOR palavras iguais (confiáveis)
    xs: list[int] = []
    ts: list[float] = []
    strong = 0
    for a0, b0, size in sm.get_matching_blocks():
        if size >= _MIN_ANCHOR:
            strong += size
            xs.append(a0); ts.append(asr_words[b0]["start"])
            xs.append(a0 + size - 1); ts.append(asr_words[b0 + size - 1]["start"])
    # sem âncoras fortes o bastante → aceita qualquer match (melhor que nada)
    if len(xs) < 2:
        for a0, b0, size in sm.get_matching_blocks():
            for k in range(size):
                xs.append(a0 + k); ts.append(asr_words[b0 + k]["start"])
    if len(xs) < 2:
        return [], 0.0

    # 3) mapa palavra_do_livro -> tempo, por interpolação entre âncoras
    ax = np.asarray(xs, dtype=float)
    at = np.asarray(ts, dtype=float)
    order = np.argsort(ax, kind="stable")
    ax, at = ax[order], at[order]
    keep = np.concatenate(([True], np.diff(ax) > 0))   # xs estritamente crescente
    ax, at = ax[keep], at[keep]
    at = np.maximum.accumulate(at)                      # tempo nunca anda pra trás
    times = np.interp(np.arange(n_ref), ax, at)         # extrapola "plano" nas pontas

    # 4) início/fim por frase
    sent_start: dict[int, float] = {}
    sent_end: dict[int, float] = {}
    for i, (_, si) in enumerate(ref):
        t = float(times[i])
        sent_start.setdefault(si, t)
        sent_end[si] = t

    audio_end = float(asr_words[-1]["end"])
    out: list[dict] = []
    for si, s in enumerate(sentences):
        start = sent_start.get(si)
        if start is None:
            start = out[-1]["end"] if out else 0.0
            end = start
        else:
            end = max(sent_end.get(si, start), start)
        out.append({"id": s["id"], "start": round(start, 3), "end": round(end, 3)})

    # 5) fim de cada frase = início da próxima (destaque contínuo); último = fim do áudio
    for i in range(len(out) - 1):
        if out[i + 1]["start"] > out[i]["end"]:
            out[i]["end"] = out[i + 1]["start"]
    if out:
        out[-1]["end"] = max(out[-1]["end"], audio_end)

    confidence = round(strong / n_ref, 3) if n_ref else 0.0
    return out, confidence
