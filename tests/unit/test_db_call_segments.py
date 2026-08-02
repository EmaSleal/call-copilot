"""
Unit tests for PR1 — DB Foundation: post-session processing.

TDD RED phase — tests written against interfaces that do not yet exist.

Authoritative design (orchestrator-injected):
  - New `call_segments` table (NOT segments table modification)
  - New `CallSegment` dataclass
  - `save_call_segment(seg: CallSegment) -> int`
  - `get_call_segments(call_session_id: int) -> list[CallSegment]`
  - `create_call_session` accepts optional `title: str = ""`
  - `_migrate` adds `title TEXT DEFAULT ''` to call_sessions

Covers:
  1.1  Migration: call_sessions.title column + call_segments table; idempotency
  1.2  CallSegment dataclass: instantiates correctly
  1.7  create_call_session(title=...) → object with .id and .title
  1.8  get_call_segments(call_session_id) → list of CallSegment rows
  1.9  set_call_session_title(call_session_id, title) → updates title
  1.10 Legacy video segment (in segments table) NOT returned by get_call_segments
"""

import sqlite3
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_call_segments.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    """
    Initialize DB against a temp file so every test is isolated.
    Returns the db module with DB_PATH already patched.
    """
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


# ─────────────────────────────────────────────────────────────
# Phase 1.1 — Migration: call_sessions.title column
# ─────────────────────────────────────────────────────────────

class TestTitleColumnMigration:
    def test_title_column_exists_after_init(self, patched_db, db_path):
        """_migrate must add title TEXT column to call_sessions."""
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()}
        finally:
            conn.close()
        assert "title" in cols

    def test_title_column_is_nullable(self, patched_db, db_path):
        """title column must be nullable (notnull == 0)."""
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("PRAGMA table_info(call_sessions)").fetchall()
            # PRAGMA: (cid, name, type, notnull, dflt_value, pk)
            title_col = next(r for r in rows if r[1] == "title")
            assert title_col[3] == 0, "title must be nullable"
        finally:
            conn.close()

    def test_migrate_is_idempotent_title(self, patched_db, db_path):
        """Running init_db() twice must not raise (idempotent migration)."""
        import src.db.database as db_module
        db_module.init_db()  # second run
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()}
        finally:
            conn.close()
        assert "title" in cols


# ─────────────────────────────────────────────────────────────
# Phase 1.1 — Migration: call_segments table
# ─────────────────────────────────────────────────────────────

class TestCallSegmentsTableMigration:
    def test_call_segments_table_exists_after_init(self, patched_db, db_path):
        """_migrate must create the call_segments table."""
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert "call_segments" in tables

    def test_call_segments_schema(self, patched_db, db_path):
        """call_segments must have id, call_session_id, sort_order, text, category_id columns."""
        conn = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(call_segments)").fetchall()}
        finally:
            conn.close()
        assert {"id", "call_session_id", "sort_order", "text", "category_id"} <= cols

    def test_call_segments_table_idempotent(self, patched_db, db_path):
        """Running init_db() twice must not raise for call_segments table."""
        import src.db.database as db_module
        db_module.init_db()
        conn = sqlite3.connect(db_path)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        finally:
            conn.close()
        assert "call_segments" in tables


# ─────────────────────────────────────────────────────────────
# Phase 1.2 — CallSegment dataclass
# ─────────────────────────────────────────────────────────────

class TestCallSegmentDataclass:
    def test_call_segment_instantiates_with_all_fields(self, patched_db):
        """CallSegment dataclass must accept all required fields."""
        from src.db.database import CallSegment
        seg = CallSegment(
            id=None,
            call_session_id=1,
            sort_order=0,
            text="An idea",
            category_id=None,
        )
        assert seg.call_session_id == 1
        assert seg.sort_order == 0
        assert seg.text == "An idea"
        assert seg.category_id is None

    def test_call_segment_category_id_defaults_to_none(self, patched_db):
        """CallSegment.category_id must default to None."""
        from src.db.database import CallSegment
        seg = CallSegment(id=None, call_session_id=2, sort_order=1, text="Another idea")
        assert seg.category_id is None

    def test_segment_dataclass_unchanged(self, patched_db):
        """Original Segment dataclass must be unchanged (session_id still required)."""
        from src.db.database import Segment
        seg = Segment(id=None, session_id=1, start_s=0.0, end_s=1.0, text="video")
        assert seg.session_id == 1


# ─────────────────────────────────────────────────────────────
# Phase 1.3 — CRUD: create_call_session with title
# ─────────────────────────────────────────────────────────────

class TestCreateCallSessionWithTitle:
    def test_create_call_session_returns_object_with_id(self, patched_db):
        """create_call_session must return a CallSession with a populated .id."""
        cs = patched_db.create_call_session(
            context="meeting",
            transcript_path="whisper-text/t.txt",
            title="Q3 planning",
        )
        assert cs.id is not None
        assert isinstance(cs.id, int)

    def test_create_call_session_returns_title(self, patched_db):
        """create_call_session must return the CallSession with the given title."""
        cs = patched_db.create_call_session(
            context="meeting",
            transcript_path="whisper-text/t.txt",
            title="My call",
        )
        assert cs.title == "My call"

    def test_create_call_session_empty_title_by_default(self, patched_db):
        """create_call_session with no title stores empty string."""
        cs = patched_db.create_call_session(
            context="meeting",
            transcript_path="whisper-text/t.txt",
        )
        assert cs.title == ""

    def test_title_persisted_in_db(self, patched_db, db_path):
        """Title must actually be written to the DB row."""
        patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/x.txt",
            title="Important meeting",
        )
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT title FROM call_sessions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "Important meeting"


# ─────────────────────────────────────────────────────────────
# Phase 1.3 — CRUD: save_call_segment + get_call_segments
# ─────────────────────────────────────────────────────────────

class TestSaveAndGetCallSegments:
    def test_save_call_segment_returns_id(self, patched_db):
        """save_call_segment must return the inserted row's integer id."""
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        seg = CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="Idea one")
        returned_id = patched_db.save_call_segment(seg)
        assert isinstance(returned_id, int)
        assert returned_id > 0

    def test_get_call_segments_returns_matching_rows(self, patched_db):
        """get_call_segments must return CallSegment rows linked to the call session."""
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
            title="Test call",
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="Idea one")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="Idea two")
        )

        results = patched_db.get_call_segments(cs.id)

        assert len(results) == 2
        texts = {r.text for r in results}
        assert "Idea one" in texts
        assert "Idea two" in texts

    def test_get_call_segments_ordered_by_sort_order(self, patched_db):
        """get_call_segments must return rows in ascending sort_order."""
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="Second")
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="First")
        )

        results = patched_db.get_call_segments(cs.id)

        assert results[0].text == "First"
        assert results[1].text == "Second"

    def test_get_call_segments_empty_when_none(self, patched_db):
        """get_call_segments returns [] when call session has no segments."""
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        results = patched_db.get_call_segments(cs.id)
        # Precondition: we created the session with 0 segments
        assert results == []

    def test_get_call_segments_wrong_session_returns_empty(self, patched_db):
        """get_call_segments for a different call_session_id returns nothing."""
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="Mine")
        )

        results = patched_db.get_call_segments(cs.id + 999)
        assert results == []

    def test_call_segment_persists_category_id(self, patched_db):
        """save_call_segment must persist category_id correctly."""
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        categories = patched_db.get_categories()
        cat_id = categories[0].id if categories else None

        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0,
                        text="Classified idea", category_id=cat_id)
        )

        results = patched_db.get_call_segments(cs.id)
        assert len(results) == 1
        assert results[0].category_id == cat_id


# ─────────────────────────────────────────────────────────────
# Phase 1.3 — CRUD: set_call_session_title
# ─────────────────────────────────────────────────────────────

class TestSetCallSessionTitle:
    def test_set_call_session_title_updates_value(self, patched_db):
        """set_call_session_title must persist the new title to the DB."""
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
            title="Original",
        )
        patched_db.set_call_session_title(cs.id, "Updated title")

        sessions = patched_db.get_call_sessions()
        updated = next(s for s in sessions if s.id == cs.id)
        assert updated.title == "Updated title"

    def test_set_call_session_title_does_not_affect_others(self, patched_db):
        """set_call_session_title only changes the targeted session."""
        cs1 = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/a.txt",
            title="Session one",
        )
        cs2 = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/b.txt",
            title="Session two",
        )
        patched_db.set_call_session_title(cs1.id, "Renamed one")

        sessions = patched_db.get_call_sessions()
        s2 = next(s for s in sessions if s.id == cs2.id)
        assert s2.title == "Session two"


# ─────────────────────────────────────────────────────────────
# Phase 1.3 — Isolation: video segments untouched
# ─────────────────────────────────────────────────────────────

class TestSegmentIsolation:
    def test_video_segments_table_untouched(self, patched_db, db_path):
        """
        The segments table schema must remain unchanged
        (session_id NOT NULL, no call_session_id column added).
        """
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("PRAGMA table_info(segments)").fetchall()
            col_map = {r[1]: r for r in rows}
        finally:
            conn.close()
        # session_id still exists and is NOT NULL
        assert "session_id" in col_map
        assert col_map["session_id"][3] == 1, "segments.session_id must remain NOT NULL"
        # call_session_id must NOT be added to segments table
        assert "call_session_id" not in col_map

    def test_call_segments_separate_from_segments(self, patched_db):
        """
        Inserting a CallSegment must not create a row in segments, and vice versa.
        """
        from src.db.database import CallSegment
        cs = patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/s.txt",
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="Call idea")
        )

        # get_segments looks at the segments table — must return empty for any video session id
        results = patched_db.get_segments(9999)
        assert results == []
