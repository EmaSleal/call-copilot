"""
Integration tests for the rolling transcript buffer in CallCopilotPipeline.

Verifies:
- At session start (no segments), TriggerEvent.recent_context is ""
- After 1+ segments, recent_context contains chronological words from those segments
- After 2+ segments, words appear in order from both segments
- Buffer respects maxlen=300 (oldest words drop off when overflowing)
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from src.core.interfaces import (
    TriggerEvent, TriggerReason, LLMResponse,
    TranscriptSegment,
)
from src.core.pipeline import CallCopilotPipeline


# ── Fake LLM that records TriggerEvent ────────────────────────────────────────

class FakeLLM:
    def __init__(self):
        self.triggers: list[TriggerEvent] = []

    async def respond(
        self,
        context: str,
        trigger: TriggerEvent,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ):
        self.triggers.append(trigger)
        yield LLMResponse(text="ok", is_partial=False)


class FakeOutput:
    async def emit(self, response: LLMResponse) -> None:
        pass


def _build_pipeline(min_words: int = 1) -> tuple[CallCopilotPipeline, FakeLLM]:
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
        min_substantial_words=min_words,
        active_profile=None,
        cooldown_seconds=0.0,
    )
    return pipeline, fake_llm


def _push_segment(pipeline: CallCopilotPipeline, text: str) -> None:
    """Simulate a final transcript segment arriving."""
    segment = TranscriptSegment(text=text, is_final=True)
    asyncio.run(pipeline._handle_segment(segment))
    # Cancel the inactivity task so it doesn't interfere
    if pipeline._inactivity_task:
        pipeline._inactivity_task.cancel()
        pipeline._inactivity_task = None


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPipelineRollingBufferRecentContext:
    def test_no_segments_recent_context_is_empty(self):
        """At session start, before any segments, TriggerEvent.recent_context is ''."""
        pipeline, fake_llm = _build_pipeline(min_words=1)
        # Manually push enough words for the trigger to fire without any segments
        pipeline._current_block = ["palabra1", "palabra2"]
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.triggers) == 1
        assert fake_llm.triggers[0].recent_context == ""

    def test_one_segment_recent_context_contains_its_words(self):
        """After one segment, recent_context includes that segment's words."""
        pipeline, fake_llm = _build_pipeline(min_words=1)
        _push_segment(pipeline, "hola mundo prueba")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.triggers) == 1
        assert "hola" in fake_llm.triggers[0].recent_context
        assert "mundo" in fake_llm.triggers[0].recent_context
        assert "prueba" in fake_llm.triggers[0].recent_context

    def test_two_segments_recent_context_chronological(self):
        """After two segments, recent_context contains words from both in order."""
        pipeline, fake_llm = _build_pipeline(min_words=1)
        _push_segment(pipeline, "primer segmento texto")
        _push_segment(pipeline, "segundo segmento texto")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.triggers) == 1
        rc = fake_llm.triggers[0].recent_context
        # Both segments' words are present
        assert "primer" in rc
        assert "segundo" in rc
        # First segment words appear before second segment words
        assert rc.index("primer") < rc.index("segundo")

    def test_buffer_survives_multiple_trigger_cycles(self):
        """Words from prior blocks remain in recent_context across trigger cycles."""
        pipeline, fake_llm = _build_pipeline(min_words=1)
        # First trigger cycle
        _push_segment(pipeline, "alfa beta gamma")
        asyncio.run(pipeline._handle_trigger())
        # Second trigger cycle with new segment
        _push_segment(pipeline, "delta epsilon zeta")
        asyncio.run(pipeline._handle_trigger())
        assert len(fake_llm.triggers) == 2
        # Second trigger must include both old and new words
        rc2 = fake_llm.triggers[1].recent_context
        assert "alfa" in rc2
        assert "delta" in rc2

    def test_buffer_maxlen_300_words_drops_oldest(self):
        """When more than 300 words are pushed, only the last 300 are kept."""
        pipeline, fake_llm = _build_pipeline(min_words=1)
        # Push 301 unique words: "word0 word1 ... word300"
        first_word = "word0"
        # First 151 words fill the buffer past maxlen
        chunk_a = " ".join(f"word{i}" for i in range(151))
        chunk_b = " ".join(f"word{i}" for i in range(151, 302))
        _push_segment(pipeline, chunk_a)
        _push_segment(pipeline, chunk_b)
        asyncio.run(pipeline._handle_trigger())
        rc = fake_llm.triggers[0].recent_context
        words = rc.split()
        assert len(words) == 300
        # The very first word must have been evicted
        assert first_word not in words
        # The last word must still be present
        assert "word301" in words
