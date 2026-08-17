"""
Unit tests for the pending_actions table and its DAO — the human-approval
queue an agent-proposed delete waits in (D2: agent writes run autonomously,
deletes always wait for a human; the agent never executes a delete
directly, see src.agent.commands for the queueing side).

RED phase: pending_actions table/DAO functions do not exist yet.
"""

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_pending_actions.db"


@pytest.fixture
def patched_db(db_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestPendingActionsTable:
    def test_table_exists_with_expected_columns(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(pending_actions)").fetchall()}
        finally:
            conn.close()
        assert {
            "id", "actor", "action", "table_name", "row_id", "reason",
            "status", "created_at", "resolved_at", "resolved_by",
        } <= col_names


class TestCreatePendingAction:
    def test_returns_pending_action_with_id_and_defaults(self, patched_db):
        pa = patched_db.create_pending_action(
            actor="agent", action="delete_category", table_name="categories", row_id=7,
            reason="0 segments, duplicate of 'Técnico'",
        )
        assert pa.id is not None
        assert pa.actor == "agent"
        assert pa.action == "delete_category"
        assert pa.table_name == "categories"
        assert pa.row_id == 7
        assert pa.reason == "0 segments, duplicate of 'Técnico'"
        assert pa.status == "pending"
        assert pa.resolved_at is None
        assert pa.resolved_by is None

    def test_reason_defaults_to_empty_string(self, patched_db):
        pa = patched_db.create_pending_action(
            actor="agent", action="delete_tool", table_name="tools", row_id=1,
        )
        assert pa.reason == ""


class TestGetPendingActions:
    def test_returns_only_matching_status_default_pending(self, patched_db):
        pa1 = patched_db.create_pending_action(
            actor="agent", action="delete_category", table_name="categories", row_id=1
        )
        pa2 = patched_db.create_pending_action(
            actor="agent", action="delete_tool", table_name="tools", row_id=2
        )
        patched_db.resolve_pending_action(pa2.id, status="approved", resolved_by="human")

        pending = patched_db.get_pending_actions()

        assert {p.id for p in pending} == {pa1.id}

    def test_status_filter_returns_resolved_actions(self, patched_db):
        pa = patched_db.create_pending_action(
            actor="agent", action="delete_category", table_name="categories", row_id=1
        )
        patched_db.resolve_pending_action(pa.id, status="rejected", resolved_by="human")

        rejected = patched_db.get_pending_actions(status="rejected")

        assert {p.id for p in rejected} == {pa.id}

    def test_no_matches_returns_empty_list(self, patched_db):
        assert patched_db.get_pending_actions() == []


class TestResolvePendingAction:
    def test_sets_status_resolved_at_and_resolved_by(self, patched_db):
        pa = patched_db.create_pending_action(
            actor="agent", action="delete_category", table_name="categories", row_id=1
        )

        patched_db.resolve_pending_action(pa.id, status="approved", resolved_by="human")

        resolved = {p.id: p for p in patched_db.get_pending_actions(status="approved")}
        assert pa.id in resolved
        assert resolved[pa.id].resolved_by == "human"
        assert resolved[pa.id].resolved_at is not None

    def test_does_not_affect_other_pending_actions(self, patched_db):
        pa1 = patched_db.create_pending_action(
            actor="agent", action="delete_category", table_name="categories", row_id=1
        )
        pa2 = patched_db.create_pending_action(
            actor="agent", action="delete_tool", table_name="tools", row_id=2
        )

        patched_db.resolve_pending_action(pa1.id, status="approved", resolved_by="human")

        still_pending = {p.id for p in patched_db.get_pending_actions()}
        assert still_pending == {pa2.id}
