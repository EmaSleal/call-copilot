"""
Unit tests for pure helpers in src/tui/tabs/pending_actions.py — the tab
that lets a human review and approve/reject what the catalog-maintenance
agent (src.agent.maintenance) queued in pending_actions (D2: agent writes
run autonomously, deletes always wait for a human).

Mirrors tests/tui/test_categories_tab.py's convention: only pure
formatting/helper functions are tested here, not DataTable/Button wiring
(same as categories.py/video.py's delete flows, which have no dedicated
TUI-level test either).

RED phase: src/tui/tabs/pending_actions.py does not exist yet.
"""

import pytest


def _pending_action(**overrides):
    from src.db.database import PendingAction
    defaults = dict(
        id=1, actor="agent", action="delete_category", table_name="categories", row_id=7,
        reason="0 segments, duplicate of 'Técnico'", status="pending",
        created_at="2026-08-16T10:30:00", resolved_at=None, resolved_by=None,
    )
    defaults.update(overrides)
    return PendingAction(**defaults)


class TestFormatPendingRow:
    def test_formats_expected_columns(self):
        from src.tui.tabs.pending_actions import format_pending_row

        pa = _pending_action()
        row = format_pending_row(pa)

        assert row == (
            "1", "delete_category", "categories:7",
            "0 segments, duplicate of 'Técnico'", "2026-08-16T10:30",
        )

    def test_truncates_created_at_to_minutes(self):
        from src.tui.tabs.pending_actions import format_pending_row

        pa = _pending_action(created_at="2026-08-16T10:30:45.123456")
        row = format_pending_row(pa)

        assert row[4] == "2026-08-16T10:30"

    def test_empty_reason_renders_as_dash(self):
        from src.tui.tabs.pending_actions import format_pending_row

        pa = _pending_action(reason="")
        row = format_pending_row(pa)

        assert row[3] == "—"
