"""
Integration tests for DB migration — profile_id column in call_sessions.
RED phase: profile_id column does not exist yet; create_call_session
does not accept profile_id kwarg yet.
"""

import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def patched_db(db_path, monkeypatch):
    """Initialize the DB against a temp file so tests are isolated."""
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestProfileIdColumnExists:
    def test_profile_id_column_exists_after_migrate(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()}
        finally:
            conn.close()
        assert "profile_id" in col_names

    def test_profile_id_column_is_nullable(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("PRAGMA table_info(call_sessions)").fetchall()
            profile_id_col = next(r for r in rows if r[1] == "profile_id")
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            # notnull == 0 means nullable
            assert profile_id_col[3] == 0, "profile_id must be nullable (notnull=0)"
        finally:
            conn.close()

    def test_migrate_is_idempotent(self, patched_db, db_path):
        """Running init_db() again must not raise (idempotent migration)."""
        import src.db.database as db_module
        # Should not raise
        db_module.init_db()
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()}
        finally:
            conn.close()
        assert "profile_id" in col_names


class TestCreateCallSessionWithProfileId:
    def test_create_call_session_accepts_profile_id(self, patched_db):
        session = patched_db.create_call_session(
            context="test context",
            transcript_path="whisper-text/test.txt",
            profile_id="reunion",
        )
        assert session.profile_id == "reunion"

    def test_create_call_session_profile_id_default_none(self, patched_db):
        session = patched_db.create_call_session(
            context="test context",
            transcript_path="whisper-text/test.txt",
        )
        assert session.profile_id is None

    def test_create_call_session_profile_id_stored_in_db(self, patched_db, db_path):
        patched_db.create_call_session(
            context="ctx",
            transcript_path="whisper-text/x.txt",
            profile_id="entrevista",
        )
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT profile_id FROM call_sessions ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "entrevista"
