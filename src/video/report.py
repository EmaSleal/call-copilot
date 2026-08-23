"""
Genera el reporte HTML de una sesión de video procesada.
Incluye: segmentos con timestamps, keyframes, badge de categoría con color,
y buscador JS del lado del cliente (sin dependencias externas).
"""

import zipfile
from pathlib import Path

from src.db.database import Category, Segment, VideoSession


def generate_html_report(
    session: VideoSession,
    segments: list[Segment],
    categories: list[Category],
    out_dir: Path,
) -> Path:
    cat_map = {c.id: c for c in categories}

    video_html = ""
    if (out_dir / "video.mp4").exists():
        video_html = '<video src="video.mp4" controls class="player"></video>'

    seg_html = ""
    for seg in segments:
        cat = cat_map.get(seg.category_id)
        badge = (
            f'<span class="badge" style="background:{cat.color}">{cat.name}</span>'
            if cat else '<span class="badge" style="background:#6b7280">Sin categoría</span>'
        )
        frame = ""
        if seg.keyframe_path and Path(seg.keyframe_path).exists():
            # ruta relativa al HTML
            rel = Path(seg.keyframe_path).name
            frame = f'<img src="{rel}" alt="keyframe" class="frame">'

        ts_start = _fmt_ts(seg.start_s)
        ts_end   = _fmt_ts(seg.end_s)
        seg_html += f"""
        <div class="segment" data-text="{_esc(seg.text.lower())}">
          {frame}
          <div class="seg-body">
            <div class="seg-meta">
              <span class="ts">{ts_start} → {ts_end}</span>
              {badge}
            </div>
            <p class="seg-text">{_esc(seg.text)}</p>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(session.title)}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem}}
  h1{{font-size:1.5rem;margin-bottom:.25rem;color:#f8fafc}}
  .meta{{color:#94a3b8;font-size:.85rem;margin-bottom:1.5rem}}
  #search{{width:100%;padding:.6rem 1rem;border-radius:.5rem;border:1px solid #334155;
           background:#1e293b;color:#f8fafc;font-size:1rem;margin-bottom:1.5rem}}
  .segment{{display:flex;gap:1rem;background:#1e293b;border-radius:.75rem;
            padding:1rem;margin-bottom:1rem;border:1px solid #334155}}
  .frame{{width:160px;height:90px;object-fit:cover;border-radius:.5rem;flex-shrink:0}}
  .player{{width:100%;max-width:640px;border-radius:.75rem;margin-bottom:1.5rem;display:block}}
  .seg-body{{flex:1}}
  .seg-meta{{display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem}}
  .ts{{font-size:.78rem;color:#64748b;font-family:monospace}}
  .badge{{font-size:.72rem;padding:.2rem .6rem;border-radius:999px;color:#fff;font-weight:600}}
  .seg-text{{line-height:1.6;color:#cbd5e1}}
  .hidden{{display:none}}
</style>
</head>
<body>
<h1>{_esc(session.title)}</h1>
<p class="meta">{session.url} &bull; {len(segments)} segmentos &bull; {session.created_at[:10]}</p>
{video_html}
<input id="search" type="text" placeholder="Buscar en la transcripción...">
<div id="segments">{seg_html}</div>
<script>
  const input = document.getElementById('search');
  const segs  = document.querySelectorAll('.segment');
  input.addEventListener('input', () => {{
    const q = input.value.toLowerCase().trim();
    segs.forEach(s => {{
      s.classList.toggle('hidden', q && !s.dataset.text.includes(q));
    }});
  }});
</script>
</body>
</html>"""

    report_path = out_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path


def export_report_zip(session_dir: Path) -> Path:
    """Empaqueta report.html + keyframes + video.mp4 (si existe) en un .zip
    autocontenido para compartir fuera de session_dir. Excluye artefactos
    internos como audio.mp3 (fuente de transcripción, sin valor para el
    reporte)."""
    report_path = session_dir / "report.html"
    if not report_path.exists():
        raise FileNotFoundError(f"No existe {report_path}")

    zip_path = session_dir / "report.zip"
    members = [report_path, *sorted(session_dir.glob("frame_*.jpg"))]
    video_path = session_dir / "video.mp4"
    if video_path.exists():
        members.append(video_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            zf.write(member, arcname=member.name)

    return zip_path


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _esc(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
