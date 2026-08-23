"""Unit tests for src/processing/live_tool_context.py — cheap, network-free
tool-mention detection + last-mention context for the live call pipeline
(docs/next-steps/feature-proposals.md point 3)."""

from unittest.mock import patch

from src.db.database import Tool
from src.db.tool_mentions import ToolMention


def _tool(id: int, name: str) -> Tool:
    from src.db.tools import normalize_tool_name

    return Tool(id=id, name=name, normalized_name=normalize_tool_name(name))


class TestDetectMentionedTools:
    def test_detects_exact_name_mentioned_in_text(self):
        from src.processing.live_tool_context import detect_mentioned_tools

        redis = _tool(1, "Redis")
        postgres = _tool(2, "PostgreSQL")

        result = detect_mentioned_tools("usamos redis para cachear", [redis, postgres])

        assert result == [redis]

    def test_no_match_returns_empty_list(self):
        from src.processing.live_tool_context import detect_mentioned_tools

        redis = _tool(1, "Redis")

        result = detect_mentioned_tools("hablemos del proyecto en general", [redis])

        assert result == []

    def test_respects_word_boundaries_not_substring_inside_another_word(self):
        """'Go' must not match inside 'Google' — a short/generic tool name
        substring-matching arbitrary words would be pure noise."""
        from src.processing.live_tool_context import detect_mentioned_tools

        go = _tool(1, "Go")

        result = detect_mentioned_tools("lo buscamos en Google", [go])

        assert result == []

    def test_matches_multiple_distinct_tools_in_same_block(self):
        from src.processing.live_tool_context import detect_mentioned_tools

        redis = _tool(1, "Redis")
        chroma = _tool(2, "Chroma")

        result = detect_mentioned_tools("migramos de redis a chroma la semana pasada", [redis, chroma])

        assert {t.id for t in result} == {1, 2}

    def test_case_insensitive(self):
        from src.processing.live_tool_context import detect_mentioned_tools

        redis = _tool(1, "Redis")

        result = detect_mentioned_tools("REDIS quedó como bottleneck", [redis])

        assert result == [redis]


class TestBuildLiveToolContext:
    def test_returns_empty_string_when_no_tools(self):
        from src.processing.live_tool_context import build_live_tool_context

        assert build_live_tool_context([]) == ""

    def test_returns_empty_string_when_tool_has_no_past_mentions(self):
        from src.processing.live_tool_context import build_live_tool_context

        redis = _tool(1, "Redis")
        with patch("src.processing.live_tool_context.get_tool_mentions", return_value=[]):
            result = build_live_tool_context([redis])

        assert result == ""

    def test_includes_most_recent_mentions_context_snippet(self):
        from src.processing.live_tool_context import build_live_tool_context

        redis = _tool(1, "Redis")
        older = ToolMention(
            id=1, tool_id=1, call_session_id=10,
            context_snippet="lo probamos como cache", created_at="2026-01-01T00:00:00",
        )
        newest = ToolMention(
            id=2, tool_id=1, call_session_id=11,
            context_snippet="tuvimos un problema de memoria con Redis", created_at="2026-02-01T00:00:00",
        )
        with patch(
            "src.processing.live_tool_context.get_tool_mentions",
            return_value=[older, newest],
        ):
            result = build_live_tool_context([redis])

        assert "tuvimos un problema de memoria con Redis" in result
        assert "lo probamos como cache" not in result
        assert "Redis" in result

    def test_joins_multiple_tools_context_on_separate_lines(self):
        from src.processing.live_tool_context import build_live_tool_context

        redis = _tool(1, "Redis")
        chroma = _tool(2, "Chroma")
        redis_mention = ToolMention(
            id=1, tool_id=1, call_session_id=10,
            context_snippet="redis se usa para sesiones", created_at="2026-01-01T00:00:00",
        )
        chroma_mention = ToolMention(
            id=2, tool_id=2, call_session_id=11,
            context_snippet="chroma para el RAG de tools", created_at="2026-01-02T00:00:00",
        )

        def fake_mentions(tool_id):
            return [redis_mention] if tool_id == 1 else [chroma_mention]

        with patch("src.processing.live_tool_context.get_tool_mentions", side_effect=fake_mentions):
            result = build_live_tool_context([redis, chroma])

        assert "redis se usa para sesiones" in result
        assert "chroma para el RAG de tools" in result
