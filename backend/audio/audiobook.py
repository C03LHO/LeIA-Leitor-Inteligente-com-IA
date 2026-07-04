"""Exporta um livro inteiro como audiolivro (M4B com capítulos, ou MP3).

Reaproveita o áudio por frase já em cache (o mesmo que a leitura usa); frases
que faltarem são sintetizadas na hora. Concatena tudo numa faixa, marca os
capítulos pelos títulos das seções e encoda com o ffmpeg (embute a capa).
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from backend.config import CACHE_DIR
from backend.tts.voices import get_active_voice_id
from backend.utils.logging import get_logger
from backend.utils.paths import pdf_result_path

logger = get_logger("audio.audiobook")

SAMPLE_RATE = 24000
_GAP_SENTENCE = 0.28   # s de silêncio entre frases
_GAP_CHAPTER = 0.9     # s de silêncio entre capítulos


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def audiobook_path(job_id: str, fmt: str) -> Path:
    d = CACHE_DIR / "audiobooks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_id}.{fmt}"


def _cover_png(job_id: str) -> Path | None:
    p = CACHE_DIR / "pdf" / f"{job_id}_cover.png"
    return p if p.exists() else None


def _chapters(result: dict) -> list[tuple[str, list[str]]]:
    """[(título_capítulo, [frases])] na ordem do livro."""
    chapters: list[tuple[str, list[str]]] = []
    for sec in result.get("sections", []):
        texts: list[str] = []
        for p in sec.get("paragraphs", []):
            for s in p.get("sentences", []):
                t = (s.get("text") or "").strip()
                if t:
                    texts.append(t)
        if texts:
            title = (sec.get("title") or "").strip() or f"Parte {len(chapters) + 1}"
            chapters.append((title, texts))
    return chapters


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def _pcm_from_wav(wav_bytes: bytes) -> bytes:
    """Extrai o PCM int16 mono 24k de um WAV de frase (o formato que a síntese
    produz). Se vier diferente, devolve vazio (a frase é pulada)."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
                return b""
            return w.readframes(w.getnframes())
    except Exception:
        return b""


def _fmt_ffmeta_time(seconds: float) -> int:
    return int(round(seconds * 1000))  # TIMEBASE 1/1000


def build_audiobook(job_id: str, fmt: str = "m4b", voice: str | None = None, progress_cb=None) -> Path:
    """Gera o audiolivro e devolve o caminho do arquivo. `progress_cb(done, total)`
    é chamado a cada frase."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg não encontrado — necessário para exportar o audiolivro.")
    fmt = "mp3" if fmt == "mp3" else "m4b"
    rp = pdf_result_path(job_id)
    if not rp.exists():
        raise RuntimeError("Livro não encontrado.")
    result = json.loads(rp.read_text(encoding="utf-8"))
    voice = voice or get_active_voice_id()
    title = (result.get("metadata", {}) or {}).get("filename") or job_id
    title = Path(title).stem
    author = (result.get("metadata", {}) or {}).get("author") or ""

    chapters = _chapters(result)
    total = sum(len(t) for _, t in chapters)
    if total == 0:
        raise RuntimeError("Este livro não tem texto para narrar.")

    from backend.tts.streamer import get_or_synthesize

    # Timeout por frase (como a fila de preparo): numa GPU lotada uma síntese
    # pode travar; sem isto a exportação penduraria para sempre. Após várias
    # travas seguidas, aborta com erro claro em vez de congelar.
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leia-export")
    stalls = 0

    raw_wav = audiobook_path(job_id, "raw.wav")
    marks: list[tuple[float, float, str]] = []  # (início, fim, título)
    done = 0
    try:
        with wave.open(str(raw_wav), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            cursor = 0.0  # segundos escritos
            for ci, (ch_title, texts) in enumerate(chapters):
                if ci:
                    out.writeframes(_silence(_GAP_CHAPTER))
                    cursor += _GAP_CHAPTER
                ch_start = cursor
                for text in texts:
                    pcm = b""
                    try:
                        pcm = _pcm_from_wav(pool.submit(get_or_synthesize, text, voice, 1.0).result(timeout=90))
                        stalls = 0
                    except FuturesTimeout:
                        stalls += 1
                        logger.warning("Frase travou na exportação (job %s, %d seguidas)", job_id, stalls)
                        pool.shutdown(wait=False, cancel_futures=True)
                        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="leia-export")
                        if stalls >= 3:
                            raise RuntimeError(
                                "A GPU está sobrecarregada e a síntese travou. Prepare a leitura "
                                "do livro primeiro (isso aquece o cache) e exporte de novo."
                            )
                    except Exception:
                        logger.exception("Falha ao obter áudio de uma frase (job %s)", job_id)
                    if pcm:
                        out.writeframes(pcm)
                        cursor += len(pcm) / 2 / SAMPLE_RATE
                    out.writeframes(_silence(_GAP_SENTENCE))
                    cursor += _GAP_SENTENCE
                    done += 1
                    if progress_cb:
                        progress_cb(done, total)
                marks.append((ch_start, cursor, ch_title))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    out_path = audiobook_path(job_id, fmt)
    if fmt == "m4b":
        _encode_m4b(raw_wav, out_path, title, author, marks, _cover_png(job_id))
    else:
        _encode_mp3(raw_wav, out_path, title, author, _cover_png(job_id))
    try:
        raw_wav.unlink()
    except OSError:
        pass
    logger.info("Audiolivro gerado: %s (%d frases, %d capítulos)", out_path.name, total, len(chapters))
    return out_path


def _write_ffmetadata(path: Path, title: str, author: str, marks: list[tuple[float, float, str]]) -> None:
    lines = [";FFMETADATA1", f"title={title}", f"artist={author or 'LeIA'}", f"album={title}", "genre=Audiobook"]
    for start, end, ch_title in marks:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={_fmt_ffmeta_time(start)}",
            f"END={_fmt_ffmeta_time(end)}",
            f"title={ch_title}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {proc.stderr[:400]}")


def _encode_m4b(raw_wav: Path, out_path: Path, title: str, author: str,
                marks: list[tuple[float, float, str]], cover: Path | None) -> None:
    meta = out_path.with_suffix(".ffmeta.txt")
    _write_ffmetadata(meta, title, author, marks)
    args = ["-i", str(raw_wav), "-i", str(meta)]
    if cover:
        args += ["-i", str(cover)]
    args += ["-map_metadata", "1"]
    if cover:
        args += ["-map", "0:a", "-map", "2:v", "-disposition:v", "attached_pic", "-c:v", "mjpeg"]
    else:
        args += ["-map", "0:a"]
    args += ["-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out_path)]
    _run_ffmpeg(args)
    try:
        meta.unlink()
    except OSError:
        pass


def _encode_mp3(raw_wav: Path, out_path: Path, title: str, author: str, cover: Path | None) -> None:
    args = ["-i", str(raw_wav)]
    if cover:
        args += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-id3v2_version", "3",
                 "-metadata:s:v", "title=capa", "-disposition:v", "attached_pic"]
    args += ["-c:a", "libmp3lame", "-b:a", "96k",
             "-metadata", f"title={title}", "-metadata", f"artist={author or 'LeIA'}",
             "-metadata", f"album={title}", str(out_path)]
    _run_ffmpeg(args)
