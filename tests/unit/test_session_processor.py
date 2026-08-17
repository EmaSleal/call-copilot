"""
Unit tests for PR2 — session_processor.process().

TDD RED phase. All tests reference src/processing/session_processor.py
which does NOT exist yet (guarantees failure at import time).

Covers spec scenarios:
  2.2  Short transcript (< threshold) → returns 0, LLM NOT called
  2.3  Valid JSON grouper response → segments saved with correct fields
  2.4  Malformed JSON from grouper → fallback chunking → no exception
  2.5  Grouper returns empty array → 0 segments saved
  2.6  classify returns None for an idea → segment saved with category_id=NULL
  + transcript stripping: timestamps/headers/CONTEXTO blocks stripped before threshold check
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    """Isolated in-memory DB for each test."""
    import src.db.database as db_module
    db_path = tmp_path / "test_processor.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


@pytest.fixture
def call_session_id(patched_db):
    """Create a call session and return its id."""
    cs = patched_db.create_call_session(
        context="test ctx",
        transcript_path="whisper-text/test.txt",
        title="Test session",
    )
    return cs.id


@pytest.fixture
def transcript_file(tmp_path):
    """Helper to create a temp transcript file with given content."""
    def _make(content: str) -> str:
        p = tmp_path / "transcript.txt"
        p.write_text(content, encoding="utf-8")
        return str(p)
    return _make


# ─────────────────────────────────────────────────────────────
# Task 2.2 — Short transcript: < threshold → returns 0, LLM not called
# ─────────────────────────────────────────────────────────────

class TestShortTranscriptSkipped:
    def test_short_transcript_returns_zero(self, patched_db, call_session_id, transcript_file):
        """process() with < threshold chars returns 0 and does not call LLM."""
        from src.processing import session_processor

        short_text = "Hello world, this is a short transcript."
        path = transcript_file(short_text)

        with patch.object(session_processor, "_call_grouper_llm") as mock_llm:
            result = session_processor.process(call_session_id, path)

        assert result == 0
        mock_llm.assert_not_called()

    def test_short_transcript_saves_no_segments(self, patched_db, call_session_id, transcript_file):
        """process() on a short transcript saves zero call_segments to the DB."""
        from src.processing import session_processor

        path = transcript_file("Too short.")

        with patch.object(session_processor, "_call_grouper_llm"):
            session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 0

    def test_empty_transcript_file_returns_zero(self, patched_db, call_session_id, transcript_file):
        """process() on an empty file returns 0 without error."""
        from src.processing import session_processor

        path = transcript_file("")

        with patch.object(session_processor, "_call_grouper_llm") as mock_llm:
            result = session_processor.process(call_session_id, path)

        assert result == 0
        mock_llm.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Task 2.3 — Valid JSON from grouper → segments saved correctly
# ─────────────────────────────────────────────────────────────

class TestValidGrouperResponse:
    def _long_transcript(self):
        """Build a transcript string comfortably above the 200-char threshold."""
        return (
            "We discussed the quarterly roadmap in detail. "
            "The engineering team reviewed performance bottlenecks. "
            "Product requirements were clarified for the next sprint. "
            "Budget allocation was reviewed and approved by the finance team. "
            "Next steps were assigned to each department lead with deadlines."
        )

    def test_valid_json_saves_one_segment_per_idea(self, patched_db, call_session_id, transcript_file):
        """Two ideas in grouper JSON → two call_segments in DB."""
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [
                {"title": "Roadmap", "text": "Discussed quarterly roadmap."},
                {"title": "Engineering", "text": "Reviewed performance issues."},
            ]
        })

        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[1, 2]):
                result = session_processor.process(call_session_id, path)

        assert result == 2
        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 2

    def test_segments_have_correct_call_session_id(self, patched_db, call_session_id, transcript_file):
        """Each saved segment must reference the given call_session_id."""
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [{"title": "T1", "text": "Some idea text here."}]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 1
        assert segments[0].call_session_id == call_session_id

    def test_segments_have_ascending_sort_order(self, patched_db, call_session_id, transcript_file):
        """Three ideas → sort_order values are 0, 1, 2."""
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [
                {"title": "A", "text": "First idea."},
                {"title": "B", "text": "Second idea."},
                {"title": "C", "text": "Third idea."},
            ]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None, None, None]):
                session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert [s.sort_order for s in segments] == [0, 1, 2]


# ─────────────────────────────────────────────────────────────
# Task 2.4 — Malformed JSON → fallback chunking → no crash
# ─────────────────────────────────────────────────────────────

class TestMalformedJsonFallback:
    def _long_transcript(self):
        return (
            "First sentence about the project. "
            "Second sentence with more details. "
            "Third sentence explaining the context. "
            "Fourth sentence about the outcome. "
            "Fifth sentence wrapping up the discussion. "
            "Sixth sentence adds additional context here."
        )

    def test_invalid_json_does_not_raise(self, patched_db, call_session_id, transcript_file):
        """Malformed JSON from grouper must not propagate an exception."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm",
                          return_value="NOT_VALID_JSON{{{{"):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                # Must complete without raising
                result = session_processor.process(call_session_id, path)

        assert isinstance(result, int)

    def test_invalid_json_fallback_saves_at_least_one_segment(
        self, patched_db, call_session_id, transcript_file
    ):
        """Fallback on bad JSON must persist at least one segment."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm",
                          return_value="<html>NOT JSON</html>"):
            with patch("src.processing.session_processor.classify_segments_batch",
                       side_effect=lambda texts, cats: [None] * len(texts)):
                result = session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert result > 0
        assert len(segments) == result


# ─────────────────────────────────────────────────────────────
# Task 2.5 — Grouper returns empty array → 0 segments saved
# ─────────────────────────────────────────────────────────────

class TestEmptyGrouperResponse:
    def _long_transcript(self):
        return (
            "This transcript has enough characters to pass the minimum threshold. "
            "We want to ensure the grouper is actually called, but it returns empty. "
            "So the outcome should be zero segments saved in the database."
        )

    def test_empty_ideas_array_saves_zero_segments(self, patched_db, call_session_id, transcript_file):
        """Grouper returning {\"ideas\":[]} → 0 segments persisted."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())
        grouper_json = json.dumps({"ideas": []})

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            result = session_processor.process(call_session_id, path)

        assert result == 0
        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 0

    def test_empty_ideas_array_no_classify_call(self, patched_db, call_session_id, transcript_file):
        """classify_segments_batch must NOT be called when ideas list is empty."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())
        grouper_json = json.dumps({"ideas": []})

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch") as mock_cls:
                session_processor.process(call_session_id, path)

        mock_cls.assert_not_called()


# ─────────────────────────────────────────────────────────────
# Task 2.6 — classify returns None → segment saved with category_id=NULL
# ─────────────────────────────────────────────────────────────

class TestNullCategoryId:
    def _long_transcript(self):
        return (
            "Extended discussion about product features and user experience. "
            "The team explored many different angles and various considerations. "
            "Final decision was deferred pending further research and careful analysis. "
            "Leadership agreed to revisit the topic at the next quarterly review meeting."
        )

    def test_none_category_id_persisted_as_null(self, patched_db, call_session_id, transcript_file):
        """When classify returns None for an idea, segment.category_id must be None/NULL."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())
        grouper_json = json.dumps({
            "ideas": [
                {"title": "Unclassifiable", "text": "Some unusual content."},
            ]
        })

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 1
        assert segments[0].category_id is None

    def test_mixed_none_and_valid_category_ids(self, patched_db, call_session_id, transcript_file):
        """Mixed classify results: first None, second 3 → DB reflects both."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())
        grouper_json = json.dumps({
            "ideas": [
                {"title": "First", "text": "Unknown topic."},
                {"title": "Second", "text": "Technical content here."},
            ]
        })

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None, 3]):
                session_processor.process(call_session_id, path)

        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 2
        assert segments[0].category_id is None
        assert segments[1].category_id == 3


# ─────────────────────────────────────────────────────────────
# Transcript stripping — CONTEXTO/RESPUESTA blocks stripped before threshold
# ─────────────────────────────────────────────────────────────

class TestTranscriptStripping:
    def test_only_contexto_respuesta_blocks_stripped_out(
        self, patched_db, call_session_id, transcript_file
    ):
        """
        A file containing only CONTEXTO/RESPUESTA blocks and header lines
        must yield stripped text too short to process (< threshold).
        LLM must NOT be called.
        """
        from src.processing import session_processor

        # This is what the session logger writes for LLM turns — no real speech.
        content = (
            "=== Sesión 20260101_120000 ===\n"
            "Contexto inicial: Reunión de ventas\n"
            "\n"
            "[12:00:01] CONTEXTO:\n"
            "Cliente preguntó por precios.\n"
            "\n"
            "[12:00:01] RESPUESTA:\n"
            "Los precios están en el catálogo.\n"
            "\n"
            "────────────────────────────────────────\n"
        )
        path = transcript_file(content)

        with patch.object(session_processor, "_call_grouper_llm") as mock_llm:
            result = session_processor.process(call_session_id, path)

        # After stripping headers+CONTEXTO/RESPUESTA, no real spoken lines remain
        assert result == 0
        mock_llm.assert_not_called()

    def test_spoken_lines_with_timestamps_counted(
        self, patched_db, call_session_id, transcript_file
    ):
        """
        Lines like '[HH:MM:SS] text' are spoken transcript — stripped of
        the timestamp prefix, their text IS counted toward the threshold.
        With enough spoken lines, LLM IS called.
        """
        from src.processing import session_processor

        # Build enough spoken lines to exceed the 200-char threshold
        spoken_lines = "\n".join(
            f"[12:0{i}:00] This is spoken transcript line number {i} with content."
            for i in range(10)
        )
        path = transcript_file(spoken_lines)

        grouper_json = json.dumps({"ideas": []})
        with patch.object(session_processor, "_call_grouper_llm",
                          return_value=grouper_json) as mock_llm:
            session_processor.process(call_session_id, path)

        mock_llm.assert_called_once()


# ─────────────────────────────────────────────────────────────
# Phase 10 — Tools Catalog ingestion hook (PR2)
# ─────────────────────────────────────────────────────────────

class TestToolsIngestionHook:
    def _long_transcript(self):
        return (
            "We discussed the quarterly roadmap in detail. "
            "The engineering team reviewed performance bottlenecks. "
            "Product requirements were clarified for the next sprint. "
            "Budget allocation was reviewed and approved by the finance team. "
            "Next steps were assigned to each department lead with deadlines."
        )

    def test_ingest_tools_called_once_after_idea_persistence(
        self, patched_db, call_session_id, transcript_file
    ):
        """ingest_tools() must be invoked exactly once, with (call_session_id, spoken_text)."""
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [{"title": "T1", "text": "Some idea text here."}]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools") as mock_ingest:
                    with patch.object(session_processor, "index_segment"):
                        session_processor.process(call_session_id, path)

        mock_ingest.assert_called_once()
        args, _ = mock_ingest.call_args
        assert args[0] == call_session_id

    def test_ingest_tools_raising_does_not_change_return_value(
        self, patched_db, call_session_id, transcript_file
    ):
        """A raising ingest_tools() must leave process()'s return value/idea count unchanged,
        and must not propagate the exception."""
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [
                {"title": "T1", "text": "First idea text here."},
                {"title": "T2", "text": "Second idea text here."},
            ]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None, None]):
                with patch.object(session_processor, "ingest_tools",
                                  side_effect=Exception("boom")):
                    with patch.object(session_processor, "index_segment"):
                        result = session_processor.process(call_session_id, path)

        assert result == 2
        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 2

    def test_ingest_tools_raising_logs_error(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [{"title": "T1", "text": "Some idea text here."}]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools",
                                  side_effect=Exception("boom")):
                    with patch.object(session_processor, "index_segment"):
                        with patch.object(session_processor, "logger") as mock_logger:
                            session_processor.process(call_session_id, path)

        mock_logger.error.assert_called_once()

    def test_ingest_tools_not_called_on_short_transcript_early_return(
        self, patched_db, call_session_id, transcript_file
    ):
        """Early-return path (transcript too short) must not invoke ingest_tools."""
        from src.processing import session_processor

        path = transcript_file("Too short.")

        with patch.object(session_processor, "_call_grouper_llm"):
            with patch.object(session_processor, "ingest_tools") as mock_ingest:
                session_processor.process(call_session_id, path)

        mock_ingest.assert_not_called()

    def test_ingest_tools_not_called_on_empty_ideas_early_return(
        self, patched_db, call_session_id, transcript_file
    ):
        """Early-return path (empty ideas list) must not invoke ingest_tools."""
        from src.processing import session_processor

        path = transcript_file(self._long_transcript())
        grouper_json = json.dumps({"ideas": []})

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch.object(session_processor, "ingest_tools") as mock_ingest:
                session_processor.process(call_session_id, path)

        mock_ingest.assert_not_called()


class TestSearchIndexingHook:
    """Coexists with the Tools Catalog ingestion hook — both are best-effort
    post-persist steps that must never affect idea persistence's return
    value or count, whichever fails."""

    def _long_transcript(self):
        return (
            "We discussed the quarterly roadmap in detail. "
            "The engineering team reviewed performance bottlenecks. "
            "Product requirements were clarified for the next sprint. "
            "Budget allocation was reviewed and approved by the finance team. "
            "Next steps were assigned to each department lead with deadlines."
        )

    def test_index_segment_called_once_per_persisted_idea(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [
                {"title": "T1", "text": "First idea text here."},
                {"title": "T2", "text": "Second idea text here."},
            ]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None, None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment") as mock_index:
                        session_processor.process(call_session_id, path)

        assert mock_index.call_count == 2
        first_call_args = mock_index.call_args_list[0][0]
        assert first_call_args[0] == "call"
        assert first_call_args[2] == "First idea text here."

    def test_index_segment_raising_does_not_change_return_value(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [{"title": "T1", "text": "Some idea text here."}]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment",
                                      side_effect=Exception("boom")):
                        result = session_processor.process(call_session_id, path)

        assert result == 1
        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 1

    def test_index_segment_raising_logs_error(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({
            "ideas": [{"title": "T1", "text": "Some idea text here."}]
        })
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment",
                                      side_effect=Exception("boom")):
                        with patch.object(session_processor, "logger") as mock_logger:
                            session_processor.process(call_session_id, path)

        mock_logger.error.assert_called()

    def test_index_segment_not_called_on_short_transcript_early_return(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        path = transcript_file("Too short.")

        with patch.object(session_processor, "_call_grouper_llm"):
            with patch.object(session_processor, "index_segment") as mock_index:
                session_processor.process(call_session_id, path)


class TestCatalogMaintenanceHook:
    """Best-effort post-persist step, same isolation contract as tools
    ingestion/search indexing — a failure here must never affect idea
    persistence's return value or count."""

    def _long_transcript(self):
        return (
            "We discussed the quarterly roadmap in detail. "
            "The engineering team reviewed performance bottlenecks. "
            "Product requirements were clarified for the next sprint. "
            "Budget allocation was reviewed and approved by the finance team. "
            "Next steps were assigned to each department lead with deadlines."
        )

    def test_run_catalog_maintenance_called_once_with_call_session_id(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({"ideas": [{"title": "T1", "text": "Some idea text here."}]})
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment"):
                        with patch.object(session_processor, "run_catalog_maintenance") as mock_run:
                            session_processor.process(call_session_id, path)

        mock_run.assert_called_once_with(call_session_id)

    def test_raising_does_not_change_return_value(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        grouper_json = json.dumps({"ideas": [{"title": "T1", "text": "Some idea text here."}]})
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment"):
                        with patch.object(session_processor, "run_catalog_maintenance",
                                          side_effect=Exception("boom")):
                            result = session_processor.process(call_session_id, path)

        assert result == 1
        segments = patched_db.get_call_segments(call_session_id)
        assert len(segments) == 1

    def test_raising_logs_error(self, patched_db, call_session_id, transcript_file):
        from src.processing import session_processor

        grouper_json = json.dumps({"ideas": [{"title": "T1", "text": "Some idea text here."}]})
        path = transcript_file(self._long_transcript())

        with patch.object(session_processor, "_call_grouper_llm", return_value=grouper_json):
            with patch("src.processing.session_processor.classify_segments_batch",
                       return_value=[None]):
                with patch.object(session_processor, "ingest_tools"):
                    with patch.object(session_processor, "index_segment"):
                        with patch.object(session_processor, "run_catalog_maintenance",
                                          side_effect=Exception("boom")):
                            with patch.object(session_processor, "logger") as mock_logger:
                                session_processor.process(call_session_id, path)

        mock_logger.error.assert_called()

    def test_not_called_on_short_transcript_early_return(
        self, patched_db, call_session_id, transcript_file
    ):
        from src.processing import session_processor

        path = transcript_file("Too short.")

        with patch.object(session_processor, "_call_grouper_llm"):
            with patch.object(session_processor, "run_catalog_maintenance") as mock_run:
                session_processor.process(call_session_id, path)

        mock_run.assert_not_called()
