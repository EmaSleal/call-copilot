"""
Unit tests — PR 1a: Storage foundation for MCP note ingestion.

TDD RED phase — tests written against `src.db.note_sessions`, which does
not exist yet.

Covers:
  1.1 normalize_note_title — case/whitespace/trailing-punctuation table
  1.1 find_note_session_by_title — dedup lookup (miss/hit/newest-wins)
"""

import sqlite3
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_note_sessions.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    """Initialize DB against a temp file so every test is isolated."""
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


# ─────────────────────────────────────────────────────────────
# normalize_note_title
# ─────────────────────────────────────────────────────────────

class TestNormalizeNoteTitle:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("React Hooks", "react hooks"),
            ("  react   hooks  ", "react hooks"),
            ("React Hooks.", "react hooks"),
        ],
    )
    def test_normalizes_to_same_key(self, patched_db, raw, expected):
        """Case, surrounding/internal whitespace and trailing punctuation
        must all collapse to the same dedup key.

        Goes through `patched_db.normalize_note_title` (the `src.db.database`
        front-door aggregator), matching the established convention for
        pure-function DAO tests (see `test_db_tools.py`'s
        `patched_db.normalize_tool_name` usage) — not a direct
        `from src.db.note_sessions import ...`. Importing the submodule
        directly, before anything has imported `src.db.database` first,
        trips the repo-wide `database.py` <-> DAO-submodule circular import
        and leaves other already-imported DAO submodules bound to an
        orphaned, unpatchable `database` module pointing at the real
        on-disk DB. Requiring `patched_db` here guarantees `src.db.database`
        is fully imported and initialized before this test touches any
        `src.db.note_sessions` symbol."""
        assert patched_db.normalize_note_title(raw) == expected

    def test_different_title_produces_different_key(self, patched_db):
        """A genuinely different title must NOT collapse to the same key
        as 'React Hooks' — proves this isn't a trivial constant-return."""
        assert patched_db.normalize_note_title("React Hook") != patched_db.normalize_note_title("React Hooks")


# ─────────────────────────────────────────────────────────────
# notes schema (spec: note-storage — fresh init creates the table)
# ─────────────────────────────────────────────────────────────

class TestNotesSchema:
    def test_notes_table_exists_after_init(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert "notes" in tables

    def test_notes_table_has_deleted_at_column(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)").fetchall()}
        finally:
            conn.close()
        assert "deleted_at" in cols


# ─────────────────────────────────────────────────────────────
# find_note_session_by_title — dedup lookup
# ─────────────────────────────────────────────────────────────

class TestFindNoteSessionByTitle:
    def test_returns_none_on_miss(self, patched_db):
        from src.db.note_sessions import find_note_session_by_title
        assert find_note_session_by_title("Nonexistent Title") is None

    def test_returns_match_with_normalized_title_variant(self, patched_db):
        """A lookup with a differently-cased/spaced title must still find
        the session created with the canonical title."""
        from src.db.note_sessions import create_note_session, find_note_session_by_title
        created = create_note_session(title="GPU Notes")

        found = find_note_session_by_title("  gpu notes ")

        assert found is not None
        assert found.id == created.id
        assert found.title == "GPU Notes"

    def test_soft_deleted_session_is_not_matched(self, patched_db):
        from src.db.note_sessions import (
            create_note_session,
            delete_note_session,
            find_note_session_by_title,
        )
        created = create_note_session(title="Old Note")
        delete_note_session(created.id)

        assert find_note_session_by_title("Old Note") is None
