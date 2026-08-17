"""
Capa de acceso a datos. SQLite compartida entre call-copilot y video transcriber.

This module owns connection lifecycle, schema DDL, migrations, view
recreation, seed data and audit logging — a single cohesive responsibility.
Per-table dataclasses and CRUD DAOs live in their own modules under
`src/db/` (categories.py, video_sessions.py, segments.py, call_sessions.py,
call_segments.py, tools.py, tool_mentions.py, pending_actions.py,
unified.py) and are re-exported below so `from src.db.database import X`
keeps working for every symbol previously defined here.

Schema:
  categories    → taxonomía editable desde la TUI
  sessions      → una sesión de video procesada
  segments      → fragmentos de transcripción con categoría asignada
  call_sessions → sesiones del copiloto de llamadas
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from src.core.paths import app_home

DB_PATH = app_home() / "data" / "app.db"


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
# Backward-compat re-exports — per-table dataclasses + DAOs now live in
# their own modules under src/db/. Kept here so `from src.db.database
# import X` keeps working for every existing caller.
# ─────────────────────────────────────────────────────────────

from src.db.categories import (
    Category,
    _assert_valid_parent,
    get_categories,
    create_category,
    update_category,
    delete_category,
)
from src.db.video_sessions import (
    VideoSession,
    create_video_session,
    delete_video_session,
    update_session_status,
    get_video_sessions,
)
from src.db.segments import (
    Segment,
    save_segment,
    get_segments,
    update_segment_category,
    get_segments_by_category,
    get_segments_by_category_global,
    get_segments_by_ids,
    search_segments,
)
from src.db.call_sessions import (
    CallSession,
    create_call_session,
    get_call_sessions,
    delete_call_session,
    set_call_session_title,
)
from src.db.call_segments import (
    CallSegment,
    save_call_segment,
    get_call_segments,
    get_call_segments_by_category_global,
    update_call_segment_category,
    get_call_segments_by_ids,
    delete_call_segment,
)
from src.db.tools import (
    Tool,
    normalize_tool_name,
    create_tool,
    find_tool_by_name,
    get_tools,
    get_tools_by_ids,
    delete_tool,
)
from src.db.tool_mentions import (
    ToolMention,
    save_tool_mention,
    get_tool_mentions,
    delete_tool_mention,
)
from src.db.pending_actions import (
    PendingAction,
    create_pending_action,
    get_pending_actions,
    resolve_pending_action,
)
from src.db.unified import (
    UnifiedSegment,
    UnifiedSession,
    get_unified_segments,
    get_unified_sessions,
)
