"""
Unit tests for LLM provider user_message format with recent_context.

Verifies:
- When recent_context is non-empty → user_message starts with "Transcripción reciente"
- When recent_context is empty → user_message starts with "Contexto de la conversación" (fallback)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.core.interfaces import TriggerEvent, TriggerReason, LLMResponse
from src.llm.openai_provider import OpenAIProvider
from src.llm.claude_provider import ClaudeProvider


# ── Helpers ──────────────────────────────────────────────────────────────────

def _collected_user_message_openai(provider: OpenAIProvider, trigger: TriggerEvent) -> str:
    """Run respond() and capture the user message sent to the OpenAI client."""
    captured = {}

    async def fake_create(**kwargs):
        captured["user"] = next(
            m["content"] for m in kwargs["messages"] if m["role"] == "user"
        )

        class FakeStream:
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration

        return FakeStream()

    provider.client = MagicMock()
    provider.client.chat = MagicMock()
    provider.client.chat.completions = MagicMock()
    provider.client.chat.completions.create = AsyncMock(side_effect=fake_create)

    async def run():
        async for _ in provider.respond("some context", trigger):
            pass

    asyncio.run(run())
    return captured["user"]


def _collected_user_message_claude(provider: ClaudeProvider, trigger: TriggerEvent) -> str:
    """Run respond() and capture the user message sent to the Claude client."""
    captured = {}

    class FakeStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        @property
        def text_stream(self):
            return self
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
        async def get_final_message(self):
            msg = MagicMock()
            msg.content = []
            return msg

    def fake_stream_ctx(**kwargs):
        captured["user"] = next(
            m["content"] for m in kwargs["messages"] if m["role"] == "user"
        )
        return FakeStream()

    provider.client = MagicMock()
    provider.client.messages = MagicMock()
    provider.client.messages.stream = MagicMock(side_effect=fake_stream_ctx)

    async def run():
        async for _ in provider.respond("some context", trigger):
            pass

    asyncio.run(run())
    return captured["user"]


# ── Fixtures ──────────────────────────────────────────────────────────────────

_TRIGGER_WITH_RECENT = TriggerEvent(
    reason=TriggerReason.SILENCE_TIMEOUT,
    context_text="current block text",
    recent_context="palabra1 palabra2 palabra3",
)

_TRIGGER_WITHOUT_RECENT = TriggerEvent(
    reason=TriggerReason.SILENCE_TIMEOUT,
    context_text="current block text",
    recent_context="",
)


# ── OpenAI provider ───────────────────────────────────────────────────────────

class TestOpenAIUserMessageRecentContext:
    def setup_method(self):
        self.provider = OpenAIProvider(api_key="test-key")

    def test_with_recent_context_message_starts_with_transcripcion(self):
        """When recent_context is non-empty, message starts with 'Transcripción reciente'."""
        msg = _collected_user_message_openai(self.provider, _TRIGGER_WITH_RECENT)
        assert msg.startswith("Transcripción reciente")

    def test_with_recent_context_contains_recent_text(self):
        """Message includes the actual recent_context text."""
        msg = _collected_user_message_openai(self.provider, _TRIGGER_WITH_RECENT)
        assert "palabra1 palabra2 palabra3" in msg

    def test_with_recent_context_contains_rag_context(self):
        """Message includes the RAG/thematic context."""
        msg = _collected_user_message_openai(self.provider, _TRIGGER_WITH_RECENT)
        assert "some context" in msg

    def test_without_recent_context_fallback_format(self):
        """When recent_context is empty, message falls back to 'Contexto de la conversación'."""
        msg = _collected_user_message_openai(self.provider, _TRIGGER_WITHOUT_RECENT)
        assert msg.startswith("Contexto de la conversación")

    def test_without_recent_context_contains_context_text(self):
        """Fallback message includes trigger.context_text."""
        msg = _collected_user_message_openai(self.provider, _TRIGGER_WITHOUT_RECENT)
        assert "current block text" in msg


# ── Claude provider ───────────────────────────────────────────────────────────

class TestClaudeUserMessageRecentContext:
    def setup_method(self):
        self.provider = ClaudeProvider(api_key="test-key")

    def test_with_recent_context_message_starts_with_transcripcion(self):
        """When recent_context is non-empty, message starts with 'Transcripción reciente'."""
        msg = _collected_user_message_claude(self.provider, _TRIGGER_WITH_RECENT)
        assert msg.startswith("Transcripción reciente")

    def test_with_recent_context_contains_recent_text(self):
        """Message includes the actual recent_context text."""
        msg = _collected_user_message_claude(self.provider, _TRIGGER_WITH_RECENT)
        assert "palabra1 palabra2 palabra3" in msg

    def test_with_recent_context_contains_rag_context(self):
        """Message includes the RAG/thematic context."""
        msg = _collected_user_message_claude(self.provider, _TRIGGER_WITH_RECENT)
        assert "some context" in msg

    def test_without_recent_context_fallback_format(self):
        """When recent_context is empty, message falls back to 'Contexto de la conversación'."""
        msg = _collected_user_message_claude(self.provider, _TRIGGER_WITHOUT_RECENT)
        assert msg.startswith("Contexto de la conversación")

    def test_without_recent_context_contains_context_text(self):
        """Fallback message includes trigger.context_text."""
        msg = _collected_user_message_claude(self.provider, _TRIGGER_WITHOUT_RECENT)
        assert "current block text" in msg
