"""
Pipeline de video transcriber.
Descarga (yt-dlp) → transcribe (Whisper) → clasifica segmentos (LLM) →
guarda en SQLite → genera reporte HTML.

Diseñado para correr en asyncio via run_in_executor, de modo que no bloquea
el event loop de la TUI mientras procesa. El callback `on_progress` permite
actualizar la barra de progreso de la TUI en tiempo real.
"""

import asyncio
import importlib.util
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

import whisper

from src.core.paths import app_home
from src.db.database import (
    Category, Segment, VideoSession,
    create_video_session, get_categories, save_segment, update_session_status,
)
from src.processing.search_indexer import index_segment
from src.video.classifier import classify_segments_batch
from src.video.report import generate_html_report

logger = logging.getLogger("unified.video_pipeline")

OUTPUT_DIR = app_home() / "data" / "videos"


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

    _check_dependencies()

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

        # 8.5. Semantic search indexing — best-effort, must never block the
        # report or the rest of the pipeline.
        _index_saved_segments(session.id, saved_segments)

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


def _index_saved_segments(session_id: int, segments: list[Segment]) -> None:
    """Best-effort semantic search indexing — never blocks the report or
    the rest of the pipeline. Coexists with the full-text SQL search."""
    try:
        for seg in segments:
            index_segment("video", seg.id, seg.text)
    except Exception as exc:
        logger.error("search indexing failed for session_id=%d: %s", session_id, exc)


# ─────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────

def _check_dependencies() -> None:
    """Valida que yt-dlp y ffmpeg estén disponibles antes de arrancar.

    Ambos se resuelven como paquetes Python del venv actual (ver
    _yt_dlp_cmd/_ffmpeg_path), no como binarios de PATH — así funcionan
    igual instalados via pip directo o via pipx (que no expone en PATH los
    entry points de las dependencias de call-copilot, solo los suyos
    propios). Sin este chequeo, la falta de alguno recién se manifiesta
    en el primer subprocess.run con un error críptico (p. ej. WinError 2
    en Windows) que no dice qué falta ni cómo resolverlo.
    """
    missing = []
    if importlib.util.find_spec("yt_dlp") is None:
        missing.append("yt-dlp")
    if importlib.util.find_spec("imageio_ffmpeg") is None:
        missing.append("imageio-ffmpeg (empaqueta ffmpeg)")
    if missing:
        raise RuntimeError(
            f"Faltan dependencias del extra 'video': {', '.join(missing)}. "
            "Reinstalá con el perfil Completo o corré: "
            "pip install -U yt-dlp imageio-ffmpeg"
        )


def _yt_dlp_cmd() -> list[str]:
    """Invoca yt-dlp como módulo del venv actual en vez de un binario de
    PATH — ver _check_dependencies.

    --extractor-args player_client=mweb + --remote-components ejs:github:
    YouTube's current anti-bot rollout breaks yt-dlp's default client
    selection — confirmed manually against a real video: the default
    "android_vr" client gets HTTP 403, "web" only exposes image formats,
    "tv" gets DRM-blocked (yt-dlp issue #12563). "mweb" is the one client
    that still exposes at least one muxed format (no PO token needed for
    it specifically), but it needs the remote JS-challenge solver enabled
    to pass YouTube's "n" parameter check — without it, formats silently
    disappear instead of erroring, which is worse. The solver script is
    cached after the first call (~17s cold, ~3s warm), well inside
    _get_title's 30s timeout.
    """
    return [
        sys.executable, "-m", "yt_dlp",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=mweb",
    ]


def _ffmpeg_path() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _get_title(url: str) -> str:
    try:
        result = subprocess.run(
            _yt_dlp_cmd() + ["--print", "title", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        title = result.stdout.strip()
        return title if title else url
    except Exception:
        return url


def _download_audio(url: str, out_dir: Path) -> Path:
    audio_path = out_dir / "audio.mp3"
    subprocess.run(_yt_dlp_cmd() + [
        "-x", "--audio-format", "mp3", "--ffmpeg-location", _ffmpeg_path(),
        "--no-playlist", "-o", str(audio_path), url
    ], check=True, capture_output=True)
    return audio_path


def _download_video(url: str, out_dir: Path) -> Optional[Path]:
    video_path = out_dir / "video.mp4"
    try:
        subprocess.run(_yt_dlp_cmd() + [
            "-f", "mp4", "--ffmpeg-location", _ffmpeg_path(),
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

    Whisper slices by time, so raw segment endings carry no grammatical
    meaning. This function scans the FULL accumulated text for the last
    sentence/clause boundary, maps it back to a segment index, and splits
    there — avoiding mid-idea cuts.

    Break priority:
    1. >= min_words AND raw segment ends with . ? !  → immediate flush
    2. >= mid_words                                  → scan full text,
                                                       split at last boundary
    3. >= max_words                                  → force split at last
                                                       boundary, or hard cut
    """
    if not segments:
        return segments

    merged: list[dict] = []
    buf: list[dict] = []
    word_count = 0

    def flush_slice(end_idx: int) -> None:
        nonlocal buf, word_count
        piece = buf[:end_idx + 1]
        merged.append({
            "start": piece[0]["start"],
            "end":   piece[-1]["end"],
            "text":  " ".join(s["text"].strip() for s in piece),
        })
        buf = buf[end_idx + 1:]
        word_count = sum(len(s["text"].split()) for s in buf)

    for seg in segments:
        buf.append(seg)
        word_count += len(seg["text"].split())
        last_char = seg["text"].rstrip()[-1:] if seg["text"].strip() else ""

        # Raw segment happens to end at a sentence boundary
        if word_count >= min_words and last_char in _SENTENCE_END:
            flush_slice(len(buf) - 1)
            continue

        # Scan full text for the last boundary past min_words
        if word_count >= mid_words:
            full_text = " ".join(s["text"].strip() for s in buf)
            wi = _last_boundary(full_text, min_words)
            if wi is not None:
                si = _word_to_seg_idx(buf, wi)
                if si < len(buf) - 1:
                    flush_slice(si)
                    continue

        # Hard cap: force split at best available boundary
        if word_count >= max_words:
            full_text = " ".join(s["text"].strip() for s in buf)
            wi = _last_boundary(full_text, min_words)
            si = _word_to_seg_idx(buf, wi) if wi is not None else len(buf) - 1
            flush_slice(si)

    if buf:
        merged.append({
            "start": buf[0]["start"],
            "end":   buf[-1]["end"],
            "text":  " ".join(s["text"].strip() for s in buf),
        })

    logger.info("merged %d raw segments → %d idea segments", len(segments), len(merged))
    return merged


def _last_boundary(text: str, min_words: int) -> int | None:
    """
    Returns the word index of the most recent (last) punctuation boundary
    in `text` that falls after `min_words`. Prefers . ? ! over , ;
    """
    words = text.split()
    best_s: int | None = None
    best_c: int | None = None
    for i in range(len(words) - 2, min_words - 1, -1):
        lc = words[i][-1:] if words[i] else ""
        if lc in _SENTENCE_END and best_s is None:
            best_s = i
        if lc in _CLAUSE_END and best_c is None:
            best_c = i
        if best_s is not None and best_c is not None:
            break
    return best_s if best_s is not None else best_c


def _word_to_seg_idx(buf: list[dict], word_idx: int) -> int:
    """Maps a word index in the concatenated buf text to a buffer segment index."""
    cum = 0
    for i, seg in enumerate(buf):
        cum += len(seg["text"].split())
        if cum > word_idx:
            return i
    return len(buf) - 1


def _extract_keyframe(video_path: Optional[Path], ts: float,
                      out_dir: Path, index: int) -> Optional[Path]:
    if not video_path or not video_path.exists():
        return None
    frame_path = out_dir / f"frame_{index:04d}.jpg"
    try:
        subprocess.run([
            _ffmpeg_path(), "-y", "-ss", str(ts),
            "-i", str(video_path),
            "-frames:v", "1", "-q:v", "3",
            str(frame_path)
        ], check=True, capture_output=True, timeout=30)
        return frame_path
    except Exception:
        return None
