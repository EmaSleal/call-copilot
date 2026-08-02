"""
Unit tests for the unified_sessions view — a read-only SQL union of
`video_sessions` and `call_sessions`, normalized to (id, source, title, created_at).
"""

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_unified_sessions.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestUnifiedSessionsViewMigration:
    def test_view_exists_after_init(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            views = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()}
        finally:
            conn.close()
        assert "unified_sessions" in views

    def test_view_recreated_idempotently(self, patched_db):
        import src.db.database as db_module
        db_module.init_db()  # second run must not raise


class TestGetUnifiedSessions:
    def test_includes_video_session(self, patched_db):
        video_session = patched_db.create_video_session(title="My video", url="http://x")

        results = patched_db.get_unified_sessions()

        video_rows = [r for r in results if r.source == "video"]
        assert len(video_rows) == 1
        assert video_rows[0].id == video_session.id
        assert video_rows[0].title == "My video"

    def test_includes_call_session(self, patched_db):
        call_session = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/x.txt", title="My call"
        )

        results = patched_db.get_unified_sessions()

        call_rows = [r for r in results if r.source == "call"]
        assert len(call_rows) == 1
        assert call_rows[0].id == call_session.id
        assert call_rows[0].title == "My call"

    def test_ordered_by_created_at_desc(self, patched_db):
        import sqlite3
        from datetime import datetime, timedelta

        conn = sqlite3.connect(patched_db.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        older = (datetime.now() - timedelta(hours=2)).isoformat()
        newer = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO call_sessions (context, transcript_path, created_at, title) VALUES (?,?,?,?)",
            ("ctx", "old.txt", older, "Older"),
        )
        conn.execute(
            "INSERT INTO video_sessions (title, url, status, created_at) VALUES (?,?,?,?)",
            ("Newer", "http://x", "done", newer),
        )
        conn.commit()
        conn.close()

        results = patched_db.get_unified_sessions()

        assert results[0].title == "Newer"
        assert results[1].title == "Older"

    def test_empty_when_no_sessions(self, patched_db):
        assert patched_db.get_unified_sessions() == []
