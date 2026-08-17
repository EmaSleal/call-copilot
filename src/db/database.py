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
    parent_id: Optional[int] = None  # subcategoría de otra si no es None (un solo nivel)
    deleted_at: Optional[str] = None


@dataclass
class VideoSession:
    id: Optional[int]
    title: str
    url: str
    status: str          # pending | processing | done | error
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    html_report: Optional[str] = None
    error_msg: Optional[str] = None
    deleted_at: Optional[str] = None


@dataclass
class Segment:
    id: Optional[int]
    session_id: int
    start_s: float
    end_s: float
    text: str
    category_id: Optional[int] = None
    keyframe_path: Optional[str] = None
    deleted_at: Optional[str] = None


@dataclass
class CallSession:
    id: Optional[int]
    context: str
    transcript_path: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chroma_collection: Optional[str] = None
    profile_id: Optional[str] = None
    title: str = ""
    deleted_at: Optional[str] = None


@dataclass
class CallSegment:
    id: Optional[int]
    call_session_id: int
    sort_order: int
    text: str
    category_id: Optional[int] = None
    deleted_at: Optional[str] = None


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
    deleted_at: Optional[str] = None


@dataclass
class ToolMention:
    id: Optional[int]
    tool_id: int
    call_session_id: int
    context_snippet: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    deleted_at: Optional[str] = None


@dataclass
class PendingAction:
    """An agent-proposed delete awaiting human approval (D2: agent writes
    run autonomously, deletes always wait for a human)."""
    id: Optional[int]
    actor: str
    action: str
    table_name: str
    row_id: int
    reason: str = ""
    status: str = "pending"  # pending | approved | rejected
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


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

        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            table_name  TEXT NOT NULL,
            row_id      INTEGER NOT NULL,
            details     TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            table_name  TEXT NOT NULL,
            row_id      INTEGER NOT NULL,
            reason      TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        );
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

    cat_cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
    if "parent_id" not in cat_cols:
        conn.execute("ALTER TABLE categories ADD COLUMN parent_id INTEGER REFERENCES categories(id)")

    for table in (
        "categories", "video_sessions", "segments",
        "call_sessions", "call_segments", "tools", "tool_mentions",
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "deleted_at" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT")

    _recreate_views(conn)


def _recreate_views(conn: sqlite3.Connection) -> None:
    """Views can't be ALTERed, so they're dropped and redefined on every
    init_db() call — cheap, and keeps a single source of truth here instead
    of drifting from the CREATE VIEW IF NOT EXISTS a prior install ran with."""
    conn.execute("DROP VIEW IF EXISTS unified_segments")
    conn.execute("""
        CREATE VIEW unified_segments AS
            SELECT id, 'video' AS source, session_id, text, category_id,
                   start_s AS position
            FROM segments
            WHERE deleted_at IS NULL
            UNION ALL
            SELECT id, 'call' AS source, call_session_id AS session_id, text, category_id,
                   CAST(sort_order AS REAL) AS position
            FROM call_segments
            WHERE deleted_at IS NULL
    """)

    conn.execute("DROP VIEW IF EXISTS unified_sessions")
    conn.execute("""
        CREATE VIEW unified_sessions AS
            SELECT id, 'video' AS source, title, created_at FROM video_sessions
            WHERE deleted_at IS NULL
            UNION ALL
            SELECT id, 'call' AS source, title, created_at FROM call_sessions
            WHERE deleted_at IS NULL
    """)


def _write_audit_log(
    conn: sqlite3.Connection, actor: str, action: str, table_name: str, row_id: int, details: str = ""
) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, action, table_name, row_id, details, created_at) VALUES (?,?,?,?,?,?)",
        (actor, action, table_name, row_id, details, datetime.now().isoformat()),
    )


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
        rows = conn.execute(
            "SELECT * FROM categories WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
    return [Category(**dict(r)) for r in rows]


def _assert_valid_parent(conn: sqlite3.Connection, cat_id: Optional[int], parent_id: Optional[int]) -> None:
    """Enforce single-level category nesting (spec: Reject two-level nesting).

    Raises ValueError when:
    - `parent_id == cat_id` (self-parent)
    - the target parent is itself a subcategory (has a non-null parent_id)
    - `cat_id` itself already has children (giving it a parent would create
      a 3-level chain through its own children)
    """
    if parent_id is None:
        return
    if cat_id is not None and parent_id == cat_id:
        raise ValueError("A category cannot be its own parent.")

    parent_row = conn.execute(
        "SELECT parent_id FROM categories WHERE id=? AND deleted_at IS NULL", (parent_id,)
    ).fetchone()
    if parent_row is not None and parent_row["parent_id"] is not None:
        raise ValueError("Cannot nest a subcategory under another subcategory (single-level only).")

    if cat_id is not None:
        has_children = conn.execute(
            "SELECT 1 FROM categories WHERE parent_id=? AND deleted_at IS NULL LIMIT 1", (cat_id,)
        ).fetchone()
        if has_children is not None:
            raise ValueError("Cannot assign a parent to a category that already has children.")


def create_category(
    name: str, description: str, color: str = "#6366f1", parent_id: Optional[int] = None
) -> Category:
    with _conn() as conn:
        _assert_valid_parent(conn, None, parent_id)
        cur = conn.execute(
            "INSERT INTO categories (name, description, color, parent_id) VALUES (?,?,?,?)",
            (name, description, color, parent_id)
        )
        return Category(
            id=cur.lastrowid, name=name, description=description, color=color, parent_id=parent_id
        )


def update_category(
    cat_id: int, name: str, description: str, color: str, parent_id: Optional[int] = None
) -> None:
    """Omitting `parent_id` clears it (promotes the category to top-level)."""
    with _conn() as conn:
        _assert_valid_parent(conn, cat_id, parent_id)
        conn.execute(
            "UPDATE categories SET name=?, description=?, color=?, parent_id=? WHERE id=?",
            (name, description, color, parent_id, cat_id)
        )


def delete_category(cat_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        # Desasignar segmentos/fragmentos que usaban esta categoría antes de borrar
        conn.execute("UPDATE segments SET category_id=NULL WHERE category_id=?", (cat_id,))
        conn.execute("UPDATE call_segments SET category_id=NULL WHERE category_id=?", (cat_id,))
        # Promover hijos a nivel superior en vez de cascadear el borrado (D2)
        conn.execute("UPDATE categories SET parent_id=NULL WHERE parent_id=?", (cat_id,))
        conn.execute(
            "UPDATE categories SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), cat_id),
        )
        _write_audit_log(conn, actor, "delete_category", "categories", cat_id)


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


def delete_video_session(session_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        now = datetime.now().isoformat()
        conn.execute("UPDATE segments SET deleted_at=? WHERE session_id=?", (now, session_id))
        conn.execute("UPDATE video_sessions SET deleted_at=? WHERE id=?", (now, session_id))
        _write_audit_log(conn, actor, "delete_video_session", "video_sessions", session_id)


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
                "SELECT * FROM video_sessions WHERE status=? AND deleted_at IS NULL ORDER BY created_at DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM video_sessions WHERE deleted_at IS NULL ORDER BY created_at DESC"
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
            "SELECT * FROM segments WHERE session_id=? AND deleted_at IS NULL ORDER BY start_s",
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
            "SELECT * FROM segments WHERE session_id=? AND category_id IS ? AND deleted_at IS NULL ORDER BY start_s",
            (session_id, category_id)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def get_segments_by_category_global(category_id: int) -> list[Segment]:
    """All Segment rows in this category across every video session (not
    scoped to one session) — used by Historial's global reclassify tool."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE category_id=? AND deleted_at IS NULL", (category_id,)
        ).fetchall()
    return [Segment(**dict(r)) for r in rows]


def get_segments_by_ids(ids: list[int]) -> list[Segment]:
    """Return Segment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM segments WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
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
            WHERE s.text LIKE ? AND s.deleted_at IS NULL
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
            "SELECT * FROM call_sessions WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [CallSession(**dict(r)) for r in rows]


def delete_call_session(call_session_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE call_segments SET deleted_at=? WHERE call_session_id=?",
            (now, call_session_id),
        )
        conn.execute("UPDATE call_sessions SET deleted_at=? WHERE id=?", (now, call_session_id))
        _write_audit_log(conn, actor, "delete_call_session", "call_sessions", call_session_id)


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
            "SELECT * FROM call_segments WHERE call_session_id=? AND deleted_at IS NULL ORDER BY sort_order",
            (call_session_id,)
        ).fetchall()
    return [CallSegment(**dict(r)) for r in rows]


def get_call_segments_by_category_global(category_id: int) -> list[CallSegment]:
    """All CallSegment rows in this category across every call session (not
    scoped to one session) — used by Historial's global reclassify tool."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM call_segments WHERE category_id=? AND deleted_at IS NULL", (category_id,)
        ).fetchall()
    return [CallSegment(**dict(r)) for r in rows]


def update_call_segment_category(segment_id: int, category_id: int) -> None:
    """Reassign a single call segment's category (used by post-hoc reclassification)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE call_segments SET category_id=? WHERE id=?",
            (category_id, segment_id)
        )


def get_call_segments_by_ids(ids: list[int]) -> list[CallSegment]:
    """Return CallSegment rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM call_segments WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: CallSegment(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete_call_segment(segment_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE call_segments SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), segment_id),
        )
        _write_audit_log(conn, actor, "delete_call_segment", "call_segments", segment_id)


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
            "SELECT * FROM tools WHERE normalized_name=? AND deleted_at IS NULL", (normalized,)
        ).fetchone()
    return Tool(**dict(row)) if row else None


def get_tools() -> list[Tool]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM tools WHERE deleted_at IS NULL ORDER BY name").fetchall()
    return [Tool(**dict(r)) for r in rows]


def get_tools_by_ids(ids: list[int]) -> list[Tool]:
    """Return Tool rows for the given ids, preserving the caller's order."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM tools WHERE id IN ({placeholders}) AND deleted_at IS NULL", ids
        ).fetchall()
    by_id = {r["id"]: Tool(**dict(r)) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def delete_tool(tool_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tools SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), tool_id),
        )
        _write_audit_log(conn, actor, "delete_tool", "tools", tool_id)


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
            "SELECT * FROM tool_mentions WHERE tool_id=? AND deleted_at IS NULL ORDER BY id",
            (tool_id,)
        ).fetchall()
    return [ToolMention(**dict(r)) for r in rows]


def delete_tool_mention(mention_id: int, actor: str = "human") -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tool_mentions SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), mention_id),
        )
        _write_audit_log(conn, actor, "delete_tool_mention", "tool_mentions", mention_id)


# ─────────────────────────────────────────────────────────────
# DAOs — Pending Actions (agent-proposed deletes awaiting human approval)
# ─────────────────────────────────────────────────────────────

def create_pending_action(
    actor: str, action: str, table_name: str, row_id: int, reason: str = ""
) -> PendingAction:
    pa = PendingAction(
        id=None, actor=actor, action=action, table_name=table_name, row_id=row_id, reason=reason
    )
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO pending_actions
               (actor, action, table_name, row_id, reason, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pa.actor, pa.action, pa.table_name, pa.row_id, pa.reason, pa.status, pa.created_at)
        )
        pa.id = cur.lastrowid
    return pa


def get_pending_actions(status: str = "pending") -> list[PendingAction]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_actions WHERE status=? ORDER BY created_at", (status,)
        ).fetchall()
    return [PendingAction(**dict(r)) for r in rows]


def resolve_pending_action(pending_id: int, status: str, resolved_by: str) -> None:
    """`status` is the caller's decision: "approved" or "rejected". Only
    updates bookkeeping — actually executing an approved delete is the
    command layer's job (src.agent.commands), since only it knows how to
    map an action name back to the real DAO delete function."""
    with _conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (status, datetime.now().isoformat(), resolved_by, pending_id),
        )


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
