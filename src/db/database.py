"""
Capa de acceso a datos. SQLite compartida entre call-copilot y video transcriber.
Toda la lógica de BD está acá — el resto del código nunca toca sqlite3 directamente.

Schema:
  categories    → taxonomía editable desde la TUI
  sessions      → una sesión de video procesada
  segments      → fragmentos de transcripción con categoría asignada
  call_sessions → sesiones del copiloto de llamadas
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path("data/app.db")


@dataclass
class Category:
    id: Optional[int]
    name: str
    description: str
    color: str = "#6366f1"  # indigo por defecto


@dataclass
class VideoSession:
    id: Optional[int]
    title: str
    url: str
    status: str          # pending | processing | done | error
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    html_report: Optional[str] = None
    error_msg: Optional[str] = None


@dataclass
class Segment:
    id: Optional[int]
    session_id: int
    start_s: float
    end_s: float
    text: str
    category_id: Optional[int] = None
    keyframe_path: Optional[str] = None


@dataclass
class CallSession:
    id: Optional[int]
    context: str
    transcript_path: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            color       TEXT NOT NULL DEFAULT '#6366f1'
        );

        CREATE TABLE IF NOT EXISTS video_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            url         TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            html_report TEXT,
            error_msg   TEXT
        );

        CREATE TABLE IF NOT EXISTS segments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     INTEGER NOT NULL REFERENCES video_sessions(id),
            start_s        REAL NOT NULL,
            end_s          REAL NOT NULL,
            text           TEXT NOT NULL,
            category_id    INTEGER REFERENCES categories(id),
            keyframe_path  TEXT
        );

        CREATE TABLE IF NOT EXISTS call_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            context         TEXT NOT NULL DEFAULT '',
            transcript_path TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );
        """)
        _seed_categories(conn)


def _seed_categories(conn: sqlite3.Connection) -> None:
    """Categorías iniciales — solo se insertan si la tabla está vacía."""
    count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if count > 0:
        return
    defaults = [
        ("Técnico",     "Contenido sobre tecnología, programación o ingeniería", "#3b82f6"),
        ("Negocio",     "Estrategia, ventas, finanzas o gestión empresarial",    "#10b981"),
        ("Tutorial",    "Guías paso a paso o contenido educativo práctico",      "#f59e0b"),
        ("Entrevista",  "Conversaciones, podcasts o paneles",                    "#8b5cf6"),
        ("Noticia",     "Noticias, análisis o cobertura de eventos actuales",    "#ef4444"),
        ("Otro",        "Contenido que no encaja en las categorías anteriores",  "#6b7280"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO categories (name, description, color) VALUES (?,?,?)",
        defaults
    )


# ─────────────────────────────────────────────────────────────
# Context manager de conexión
# ─────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# DAOs — Categories
# ─────────────────────────────────────────────────────────────

def get_categories() -> list[Category]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return [Category(**dict(r)) for r in rows]


def create_category(name: str, description: str, color: str = "#6366f1") -> Category:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO categories (name, description, color) VALUES (?,?,?)",
            (name, description, color)
        )
        return Category(id=cur.lastrowid, name=name, description=description, color=color)


def update_category(cat_id: int, name: str, description: str, color: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE categories SET name=?, description=?, color=? WHERE id=?",
            (name, description, color, cat_id)
        )


def delete_category(cat_id: int) -> None:
    with _conn() as conn:
        # Desasignar segmentos que usaban esta categoría antes de borrar
        conn.execute("UPDATE segments SET category_id=NULL WHERE category_id=?", (cat_id,))
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))


# ─────────────────────────────────────────────────────────────
# DAOs — Video Sessions
# ─────────────────────────────────────────────────────────────

def create_video_session(title: str, url: str) -> VideoSession:
    s = VideoSession(id=None, title=title, url=url, status="pending")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO video_sessions (title, url, status, created_at) VALUES (?,?,?,?)",
            (s.title, s.url, s.status, s.created_at)
        )
        s.id = cur.lastrowid
    return s


def update_session_status(session_id: int, status: str,
                           html_report: str = None, error_msg: str = None) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE video_sessions SET status=?, html_report=?, error_msg=? WHERE id=?",
            (status, html_report, error_msg, session_id)
        )


def get_video_sessions(status_filter: str = None) -> list[VideoSession]:
    with _conn() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM video_sessions WHERE status=? ORDER BY created_at DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM video_sessions ORDER BY created_at DESC"
            ).fetchall()
    return [VideoSession(**dict(r)) for r in rows]


# ─────────────────────────────────────────────────────────────
# DAOs — Segments
# ─────────────────────────────────────────────────────────────

def save_segment(seg: Segment) -> Segment:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO segments
               (session_id, start_s, end_s, text, category_id, keyframe_path)
               VALUES (?,?,?,?,?,?)""",
            (seg.session_id, seg.start_s, seg.end_s,
             seg.text, seg.category_id, seg.keyframe_path)
        )
        seg.id = cur.lastrowid
    return seg


def get_segments(session_id: int) -> list[Segment]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id=? ORDER BY start_s",
            (session_id,)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def search_segments(query: str, category_id: int = None) -> list[dict]:
    """Búsqueda de texto en segmentos, con join a sesión y categoría."""
    with _conn() as conn:
        sql = """
            SELECT s.*, c.name as cat_name, c.color as cat_color,
                   vs.title as session_title, vs.url as session_url
            FROM segments s
            LEFT JOIN categories c ON s.category_id = c.id
            LEFT JOIN video_sessions vs ON s.session_id = vs.id
            WHERE s.text LIKE ?
        """
        params: list = [f"%{query}%"]
        if category_id:
            sql += " AND s.category_id = ?"
            params.append(category_id)
        sql += " ORDER BY vs.created_at DESC, s.start_s"
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────
# DAOs — Call Sessions
# ─────────────────────────────────────────────────────────────

def create_call_session(context: str, transcript_path: str) -> CallSession:
    cs = CallSession(id=None, context=context, transcript_path=transcript_path)
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, created_at) VALUES (?,?,?)",
            (cs.context, cs.transcript_path, cs.created_at)
        )
        cs.id = cur.lastrowid
    return cs


def get_call_sessions() -> list[CallSession]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_sessions ORDER BY created_at DESC"
        ).fetchall()
    return [CallSession(**dict(r)) for r in rows]
