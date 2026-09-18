"""
Unit tests — PR 1b: `save_note` ingestion (src/processing/note_ingestion.py).

TDD RED phase — tests written against `src.processing.note_ingestion`,
which does not exist yet.

Covers (spec: note-ingestion):
  2.1 create — new title creates a note session + segments, indexed,
      no LLM call
  2.1 dedup/append — repeat call with a normalized-title match appends
      instead of duplicating
  2.1 reject empty/whitespace segments — no title-only note created
  2.1 reject empty/whitespace title
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def patched_db(tmp_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_note_ingestion.db")
    db_module.init_db()
    return db_module


@pytest.fixture
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def mock_segments_store():
    """Patches SegmentsSearchStore at the note_ingestion module boundary so
    tests stay fast/deterministic — same pattern as
    tests/unit/test_search_indexer.py."""
    mock_store = MagicMock()
    mock_store.add_segment = AsyncMock(return_value=True)
    mock_store_cls = MagicMock(return_value=mock_store)
    with patch("src.processing.note_ingestion.SegmentsSearchStore", mock_store_cls):
        yield mock_store


class TestSaveNoteCreate:
    def test_new_title_creates_session_and_segments(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        note, added, created = save_note("React Hooks", ["Segment one", "Segment two"])

        assert created is True
        assert added == 2
        assert note.title == "React Hooks"
        stored = patched_db.get_note_segments(note.id)
        assert [s.text for s in stored] == ["Segment one", "Segment two"]

    def test_indexes_each_segment_into_segments_search_store_with_source_note(
        self, patched_db, no_openai_key, mock_segments_store
    ):
        from src.processing.note_ingestion import save_note

        note, _added, _created = save_note("GPU Notes", ["about CUDA", "about cuDNN"])

        stored = patched_db.get_note_segments(note.id)
        assert mock_segments_store.add_segment.await_count == 2
        mock_segments_store.add_segment.assert_any_await("note", stored[0].id, "about CUDA")
        mock_segments_store.add_segment.assert_any_await("note", stored[1].id, "about cuDNN")

    def test_never_calls_an_llm(self, patched_db, no_openai_key, mock_segments_store):
        """This module is pure storage + indexing — it must not import or
        call any LLM backend."""
        from src.processing import note_ingestion

        assert not hasattr(note_ingestion, "call_llm_backend")


class TestSaveNoteDedupAppend:
    def test_repeat_call_with_normalized_title_appends(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        first_note, _added, first_created = save_note("GPU Notes", ["first segment"])
        second_note, added, second_created = save_note("  gpu notes ", ["second segment"])

        assert first_created is True
        assert second_created is False
        assert second_note.id == first_note.id
        assert added == 1
        assert len(patched_db.get_note_sessions()) == 1
        stored = patched_db.get_note_segments(first_note.id)
        assert [s.text for s in stored] == ["first segment", "second segment"]
        assert [s.sort_order for s in stored] == [0, 1]

    def test_different_title_creates_a_new_session(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        first_note, _added, _created = save_note("GPU Notes", ["a"])
        second_note, _added2, second_created = save_note("CPU Notes", ["b"])

        assert second_created is True
        assert second_note.id != first_note.id
        assert len(patched_db.get_note_sessions()) == 2


class TestSaveNoteValidation:
    def test_empty_segments_list_raises_value_error(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        with pytest.raises(ValueError):
            save_note("Some Title", [])

        assert patched_db.get_note_sessions() == []

    def test_whitespace_only_segments_raise_value_error(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        with pytest.raises(ValueError):
            save_note("Some Title", ["  ", ""])

        assert patched_db.get_note_sessions() == []

    def test_empty_title_raises_value_error(self, patched_db, no_openai_key, mock_segments_store):
        from src.processing.note_ingestion import save_note

        with pytest.raises(ValueError):
            save_note("   ", ["a segment"])

        assert patched_db.get_note_sessions() == []
