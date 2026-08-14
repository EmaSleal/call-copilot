"""
Capa de acceso a datos. SQLite compartida entre call-copilot y video transcriber.
Toda la lógica de BD está acá — el resto del código nunca toca sqlite3 directamente.

Schema:
  categories    → taxonomía editable desde la TUI
  sessions      → una sesión de video procesada
  segments      → fragmentos de transcripción con categoría asignada
  call_sessions → sesiones del copiloto de llamadas
"""

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.paths import app_home

DB_PATH = app_home() / "data" / "app.db"


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
    chroma_collection: Optional[str] = None
    profile_id: Optional[str] = None
    title: str = ""


@dataclass
class CallSegment:
    id: Optional[int]
    call_session_id: int
    sort_order: int
    text: str
    category_id: Optional[int] = None


@dataclass
class Tool:
    id: Optional[int]
    name: str
    normalized_name: str
    category: str = ""
    description: str = ""
    summary: str = ""
    tags: str = ""  # JSON-encoded list
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ToolMention:
    id: Optional[int]
    tool_id: int
    call_session_id: int
    context_snippet: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class UnifiedSegment:
    """Read-only row from the `unified_segments` view (video + call, same categories)."""
    id: int
    source: str          # "video" | "call"
    session_id: int
    text: str
    category_id: Optional[int]
    position: float


@dataclass
class UnifiedSession:
    """Read-only row from the `unified_sessions` view (video + call)."""
    id: int
    source: str          # "video" | "call"
    title: str
    created_at: str


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
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            context             TEXT NOT NULL DEFAULT '',
            transcript_path     TEXT NOT NULL,
            chroma_collection   TEXT,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS call_segments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            call_session_id INTEGER NOT NULL REFERENCES call_sessions(id),
            sort_order      INTEGER NOT NULL,
            text            TEXT NOT NULL,
            category_id     INTEGER REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS tools (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            category        TEXT NOT NULL DEFAULT '',
            description     TEXT NOT NULL DEFAULT '',
            summary         TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_mentions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_id          INTEGER NOT NULL REFERENCES tools(id),
            call_session_id  INTEGER NOT NULL,
            context_snippet  TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL
        );

        CREATE VIEW IF NOT EXISTS unified_segments AS
            SELECT id, 'video' AS source, session_id, text, category_id,
                   start_s AS position
            FROM segments
            UNION ALL
            SELECT id, 'call' AS source, call_session_id AS session_id, text, category_id,
                   CAST(sort_order AS REAL) AS position
            FROM call_segments;

        CREATE VIEW IF NOT EXISTS unified_sessions AS
            SELECT id, 'video' AS source, title, created_at FROM video_sessions
            UNION ALL
            SELECT id, 'call' AS source, title, created_at FROM call_sessions;
        """)
        _seed_categories(conn)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent schema migrations.

    Each guard reads PRAGMA table_info once per table and only issues ALTER
    TABLE when the column is absent — safe to run on every init_db() call.
    """
    call_session_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()
    }
    if "chroma_collection" not in call_session_cols:
        conn.execute("ALTER TABLE call_sessions ADD COLUMN chroma_collection TEXT")
    if "profile_id" not in call_session_cols:
        conn.execute("ALTER TABLE call_sessions ADD COLUMN profile_id TEXT")
    if "title" not in call_session_cols:
        conn.execute("ALTER TABLE call_sessions ADD COLUMN title TEXT DEFAULT ''")


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


def delete_video_session(session_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM segments WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM video_sessions WHERE id=?", (session_id,))


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


def update_segment_category(segment_id: int, category_id: int) -> None:
    """Reassign a single segment's category (used by post-hoc reclassification)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE segments SET category_id=? WHERE id=?",
            (category_id, segment_id)
        )


def get_segments_by_category(session_id: int, category_id: Optional[int]) -> list[Segment]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id=? AND category_id IS ? ORDER BY start_s",
            (session_id, category_id)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def get_segments_by_ids(ids: list[int]) -> list[Segment]:
    """Return Segment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM segments WHERE id IN ({placeholders})", ids
        ).fetchall()
    by_id = {r["id"]: Segment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


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

def create_call_session(
    context: str,
    transcript_path: str,
    chroma_collection: str = "",
    profile_id: Optional[str] = None,
    title: str = "",
) -> CallSession:
    cs = CallSession(
        id=None,
        context=context,
        transcript_path=transcript_path,
        chroma_collection=chroma_collection,
        profile_id=profile_id,
        title=title,
    )
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, chroma_collection, profile_id, created_at, title) VALUES (?,?,?,?,?,?)",
            (cs.context, cs.transcript_path, cs.chroma_collection, cs.profile_id, cs.created_at, cs.title)
        )
        cs.id = cur.lastrowid
    return cs


def get_call_sessions() -> list[CallSession]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_sessions ORDER BY created_at DESC"
        ).fetchall()
    return [CallSession(**dict(r)) for r in rows]


def set_call_session_title(call_session_id: int, title: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE call_sessions SET title=? WHERE id=?",
            (title, call_session_id)
        )


# ─────────────────────────────────────────────────────────────
# DAOs — Call Segments
# ─────────────────────────────────────────────────────────────

def save_call_segment(seg: CallSegment) -> int:
    """Insert a CallSegment row and return its new id."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO call_segments (call_session_id, sort_order, text, category_id)
               VALUES (?,?,?,?)""",
            (seg.call_session_id, seg.sort_order, seg.text, seg.category_id)
        )
        return cur.lastrowid


def get_call_segments(call_session_id: int) -> list[CallSegment]:
    """Return all CallSegment rows for the given call session, ordered by sort_order."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_segments WHERE call_session_id=? ORDER BY sort_order",
            (call_session_id,)
        ).fetchall()
    return [CallSegment(**dict(r)) for r in rows]


def get_call_segments_by_ids(ids: list[int]) -> list[CallSegment]:
    """Return CallSegment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM call_segments WHERE id IN ({placeholders})", ids
        ).fetchall()
    by_id = {r["id"]: CallSegment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


# ─────────────────────────────────────────────────────────────
# DAOs — Tools Catalog
# ─────────────────────────────────────────────────────────────

def normalize_tool_name(name: str) -> str:
    """Lowercase, strip, collapse internal whitespace, strip trailing punctuation."""
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]+$", "", s)
    return s.strip()


def create_tool(t: Tool) -> Tool:
    """Insert a new Tool row and set its .id."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO tools (name, normalized_name, category, description, summary, tags, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (t.name, t.normalized_name, t.category, t.description, t.summary, t.tags, t.created_at)
        )
        t.id = cur.lastrowid
    return t


def find_tool_by_name(name: str) -> Optional[Tool]:
    """Look up a Tool by normalized name; returns None on miss."""
    normalized = normalize_tool_name(name)
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM tools WHERE normalized_name=?", (normalized,)
        ).fetchone()
    return Tool(**dict(row)) if row else None


def get_tools() -> list[Tool]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM tools ORDER BY name").fetchall()
    return [Tool(**dict(r)) for r in rows]


def get_tools_by_ids(ids: list[int]) -> list[Tool]:
    """Return Tool rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tools WHERE id IN ({placeholders})", ids
        ).fetchall()
    by_id = {r["id"]: Tool(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def save_tool_mention(m: ToolMention) -> int:
    """Insert a ToolMention row and return its new id. No cap — unlimited retention."""
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO tool_mentions (tool_id, call_session_id, context_snippet, created_at)
               VALUES (?,?,?,?)""",
            (m.tool_id, m.call_session_id, m.context_snippet, m.created_at)
        )
        return cur.lastrowid


def get_tool_mentions(tool_id: int) -> list[ToolMention]:
    """Return all ToolMention rows for a tool, ordered oldest-first. Unbounded."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_mentions WHERE tool_id=? ORDER BY id",
            (tool_id,)
        ).fetchall()
    return [ToolMention(**dict(r)) for r in rows]


# ─────────────────────────────────────────────────────────────
# DAOs — Unified Segments (read-only view over segments + call_segments)
# ─────────────────────────────────────────────────────────────

def get_unified_segments(
    source: Optional[str] = None, session_id: Optional[int] = None
) -> list[UnifiedSegment]:
    """
    Return rows from the unified_segments view, optionally filtered by source
    ('video'|'call') and/or session_id. Since video_sessions.id and
    call_sessions.id are independent sequences, filtering by session_id alone
    without source could mix rows from different sources that share the same id.
    """
    clauses = []
    params: list = []
    if source:
        clauses.append("source=?")
        params.append(source)
    if session_id is not None:
        clauses.append("session_id=?")
        params.append(session_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM unified_segments {where} ORDER BY session_id, position",
            params
        ).fetchall()
    return [UnifiedSegment(**dict(r)) for r in rows]


def get_unified_sessions() -> list[UnifiedSession]:
    """Return rows from the unified_sessions view, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM unified_sessions ORDER BY created_at DESC"
        ).fetchall()
    return [UnifiedSession(**dict(r)) for r in rows]
