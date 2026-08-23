"""Integration tests for CallCopilotPipeline._handle_trigger's live
tool-mention context injection (docs/next-steps/feature-proposals.md point 3).

Follows the same harness as tests/integration/test_pipeline_rolling_buffer.py:
`_handle_trigger()` is exercised directly with a hand-set `_current_block`,
bypassing audio/STT/start(), so `_known_tools` is seeded manually the same
way `_current_block` already is in that file.
"""

import asyncio
from unittest.mock import MagicMock, patch

from src.core.interfaces import LLMResponse
from src.core.pipeline import CallCopilotPipeline
from src.db.database import Tool
from src.db.tool_mentions import ToolMention
from src.db.tools import normalize_tool_name


class FakeLLM:
    def __init__(self):
        self.contexts: list[str] = []

    async def respond(
        self,
        context: str,
        trigger,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ):
        self.contexts.append(context)
        yield LLMResponse(text="ok", is_partial=False)


class FakeOutput:
    async def emit(self, response: LLMResponse) -> None:
        pass


def _tool(id: int, name: str) -> Tool:
    return Tool(id=id, name=name, normalized_name=normalize_tool_name(name))


def _build_pipeline(known_tools: list[Tool]) -> tuple[CallCopilotPipeline, FakeLLM]:
    fake_llm = FakeLLM()
    pipeline = CallCopilotPipeline(
        audio_source=MagicMock(),
        vad=MagicMock(),
        stt=MagicMock(),
        trigger=MagicMock(),
        llm=fake_llm,
        output=FakeOutput(),
        llm_enabled=True,
        initial_context="",
        min_substantial_words=1,
        active_profile=None,
        cooldown_seconds=0.0,
    )
    pipeline._known_tools = known_tools
    return pipeline, fake_llm


class TestLiveToolContextInjection:
    def test_mentioned_tool_with_past_context_is_added_to_llm_context(self):
        redis = _tool(1, "Redis")
        pipeline, fake_llm = _build_pipeline([redis])
        pipeline._current_block = ["usamos", "redis", "para", "cachear", "sesiones"]

        mention = ToolMention(
            id=1, tool_id=1, call_session_id=10,
            context_snippet="tuvimos un problema de memoria con Redis",
            created_at="2026-02-01T00:00:00",
        )
        with patch(
            "src.processing.live_tool_context.get_tool_mentions",
            return_value=[mention],
        ):
            asyncio.run(pipeline._handle_trigger())

        assert len(fake_llm.contexts) == 1
        assert "tuvimos un problema de memoria con Redis" in fake_llm.contexts[0]

    def test_no_mention_leaves_context_unchanged(self):
        redis = _tool(1, "Redis")
        pipeline, fake_llm = _build_pipeline([redis])
        pipeline._current_block = ["hablemos", "del", "roadmap", "general"]

        with patch("src.processing.live_tool_context.get_tool_mentions") as mocked:
            asyncio.run(pipeline._handle_trigger())

        mocked.assert_not_called()
        assert len(fake_llm.contexts) == 1
        assert "roadmap" in fake_llm.contexts[0]

    def test_tool_with_no_past_mentions_does_not_add_empty_section(self):
        redis = _tool(1, "Redis")
        pipeline, fake_llm = _build_pipeline([redis])
        pipeline._current_block = ["probamos", "redis", "recién"]

        with patch("src.processing.live_tool_context.get_tool_mentions", return_value=[]):
            asyncio.run(pipeline._handle_trigger())

        assert fake_llm.contexts[0].strip() == "probamos redis recién"
