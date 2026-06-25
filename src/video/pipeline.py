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
from src.video.classifier import classify_segment
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
        segments_raw = result.get("segments", [])

        # 6. Obtener categorías de BD una sola vez
        categories: list[Category] = get_categories()
        n = len(segments_raw)

        # 7. Por cada segmento: keyframe + clasificación + guardado
        saved_segments: list[Segment] = []
        for i, seg in enumerate(segments_raw):
            pct = 0.40 + (i / max(n, 1)) * 0.45
            progress(f"Procesando segmento {i+1}/{n}...", pct)

            # Extraer keyframe al punto medio del segmento
            mid = (seg["start"] + seg["end"]) / 2
            frame_path = _extract_keyframe(video_path, mid, session_dir, i)

            # Clasificar con LLM
            cat_id = classify_segment(seg["text"], categories) if categories else None

            # Guardar en BD
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

        # 8. Generar reporte HTML
        progress("Generando reporte HTML...", 0.88)
        html_path = generate_html_report(session, saved_segments, categories, session_dir)

        # 9. Marcar sesión como completada
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
