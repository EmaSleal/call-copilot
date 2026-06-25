"""
Pipeline de video transcriber.
Descarga (yt-dlp) → transcribe (Whisper) → clasifica segmentos (LLM) →
guarda en SQLite → genera reporte HTML.

Diseñado para correr en asyncio via run_in_executor, de modo que no bloquea
el event loop de la TUI mientras procesa. El callback `on_progress` permite
actualizar la barra de progreso de la TUI en tiempo real.
"""

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import whisper

from src.db.database import (
    Category, Segment, VideoSession,
    create_video_session, get_categories, save_segment, update_session_status,
)
from src.video.classifier import classify_segments_batch
from src.video.report import generate_html_report

logger = logging.getLogger("unified.video_pipeline")

OUTPUT_DIR = Path("data/videos")


def run_pipeline(
    url: str,
    model_size: str = "base",
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> VideoSession:
    """
    Punto de entrada sincrónico. Llamarlo siempre desde run_in_executor.

    on_progress(mensaje, porcentaje_0_a_1) se llama en cada etapa
    para que la TUI pueda actualizar la barra de progreso.
    """
    def progress(msg: str, pct: float):
        logger.info("[%.0f%%] %s", pct * 100, msg)
        if on_progress:
            on_progress(msg, pct)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Obtener título del video
    progress("Obteniendo información del video...", 0.0)
    title = _get_title(url)

    # 2. Crear registro en BD
    session = create_video_session(title=title, url=url)
    session_dir = OUTPUT_DIR / str(session.id)
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 3. Descargar audio
        progress("Descargando audio...", 0.05)
        audio_path = _download_audio(url, session_dir)

        # 4. Descargar video (para keyframes)
        progress("Descargando video...", 0.15)
        video_path = _download_video(url, session_dir)

        # 5. Transcribir
        progress("Cargando modelo Whisper...", 0.25)
        model = whisper.load_model(model_size)
        progress("Transcribiendo...", 0.30)
        result = model.transcribe(str(audio_path), verbose=False)
        segments_raw = _merge_segments(result.get("segments", []))
        progress(f"Segmentos agrupados: {len(segments_raw)}...", 0.38)

        # 6. Obtener categorías de BD una sola vez
        categories: list[Category] = get_categories()
        n = len(segments_raw)

        # 7. Clasificar todos los segmentos en batch (ceil(n/30) llamadas al LLM)
        progress("Clasificando segmentos...", 0.40)
        texts = [s["text"] for s in segments_raw]
        cat_ids = classify_segments_batch(texts, categories) if categories else [None] * n

        # 8. Extraer keyframes y guardar en BD
        saved_segments: list[Segment] = []
        for i, (seg, cat_id) in enumerate(zip(segments_raw, cat_ids)):
            pct = 0.55 + (i / max(n, 1)) * 0.30
            progress(f"Guardando segmento {i+1}/{n}...", pct)

            mid = (seg["start"] + seg["end"]) / 2
            frame_path = _extract_keyframe(video_path, mid, session_dir, i)

            saved = save_segment(Segment(
                id=None,
                session_id=session.id,
                start_s=seg["start"],
                end_s=seg["end"],
                text=seg["text"],
                category_id=cat_id,
                keyframe_path=str(frame_path) if frame_path else None,
            ))
            saved_segments.append(saved)

        # 9. Generar reporte HTML
        progress("Generando reporte HTML...", 0.88)
        html_path = generate_html_report(session, saved_segments, categories, session_dir)

        # 10. Marcar sesión como completada
        update_session_status(session.id, "done", html_report=str(html_path))
        session.status = "done"
        session.html_report = str(html_path)
        progress("Completado.", 1.0)

    except Exception as e:
        logger.error("error en pipeline de video session_id=%d: %s", session.id, e)
        update_session_status(session.id, "error", error_msg=str(e))
        session.status = "error"
        session.error_msg = str(e)
        raise

    return session


# ─────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────

def _get_title(url: str) -> str:
    try:
        result = subprocess.run(
            ["yt-dlp", "--print", "title", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        title = result.stdout.strip()
        return title if title else url
    except Exception:
        return url


def _download_audio(url: str, out_dir: Path) -> Path:
    audio_path = out_dir / "audio.mp3"
    subprocess.run([
        "yt-dlp", "-x", "--audio-format", "mp3",
        "--no-playlist", "-o", str(audio_path), url
    ], check=True, capture_output=True)
    return audio_path


def _download_video(url: str, out_dir: Path) -> Optional[Path]:
    video_path = out_dir / "video.mp4"
    try:
        subprocess.run([
            "yt-dlp", "-f", "mp4",
            "--no-playlist", "-o", str(video_path), url
        ], check=True, capture_output=True, timeout=300)
        return video_path
    except Exception as e:
        logger.warning("no se pudo descargar video para keyframes: %s", e)
        return None


_SENTENCE_END = frozenset(".?!")
_CLAUSE_END   = frozenset(",;")


def _merge_segments(
    segments: list[dict],
    min_words: int = 40,
    mid_words: int = 70,
    max_words: int = 120,
) -> list[dict]:
    """
    Merges Whisper segments into complete-idea segments.

    Break priority (first match wins):
    1. >= min_words AND ends with . ? !  → natural sentence break
    2. >= mid_words AND ends with , ;    → clause break
    3. >= max_words                      → forced break, scanning back for
                                           the last sentence/clause boundary
                                           before cutting hard
    """
    if not segments:
        return segments

    merged: list[dict] = []
    buf: list[dict] = []
    word_count = 0

    def flush(b: list[dict]) -> None:
        merged.append({
            "start": b[0]["start"],
            "end":   b[-1]["end"],
            "text":  " ".join(s["text"].strip() for s in b),
        })

    for seg in segments:
        buf.append(seg)
        word_count += len(seg["text"].split())
        last_char = seg["text"].rstrip()[-1:] if seg["text"].strip() else ""

        if word_count >= min_words and last_char in _SENTENCE_END:
            flush(buf); buf = []; word_count = 0
        elif word_count >= mid_words and last_char in _CLAUSE_END:
            flush(buf); buf = []; word_count = 0
        elif word_count >= max_words:
            split_at = _find_split(buf, min_words)
            if split_at is not None:
                flush(buf[:split_at + 1])
                buf = buf[split_at + 1:]
                word_count = sum(len(s["text"].split()) for s in buf)
            else:
                flush(buf); buf = []; word_count = 0

    if buf:
        flush(buf)

    logger.info("merged %d raw segments → %d idea segments", len(segments), len(merged))
    return merged


def _find_split(buf: list[dict], min_words: int) -> int | None:
    """
    Scans buf backwards for the best split index: last segment ending with
    . ? ! (preferred) or , ; (fallback), with at least min_words before it.
    """
    cum, total = [], 0
    for s in buf:
        total += len(s["text"].split())
        cum.append(total)

    best_sentence: int | None = None
    best_clause:   int | None = None

    for i in range(len(buf) - 2, -1, -1):
        if cum[i] < min_words:
            break
        lc = buf[i]["text"].rstrip()[-1:] if buf[i]["text"].strip() else ""
        if lc in _SENTENCE_END and best_sentence is None:
            best_sentence = i
        if lc in _CLAUSE_END and best_clause is None:
            best_clause = i
        if best_sentence is not None and best_clause is not None:
            break

    return best_sentence if best_sentence is not None else best_clause


def _extract_keyframe(video_path: Optional[Path], ts: float,
                      out_dir: Path, index: int) -> Optional[Path]:
    if not video_path or not video_path.exists():
        return None
    frame_path = out_dir / f"frame_{index:04d}.jpg"
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(ts),
            "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3",
            str(frame_path)
        ], check=True, capture_output=True, timeout=30)
        return frame_path
    except Exception:
        return None
