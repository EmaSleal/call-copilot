"""
Unit tests for LLM provider system-prompt composition.
RED phase: respond() on both providers does not yet accept
system_prompt_addon or conservative_mode kwargs.

We test the composed system prompt by inspecting the call made to the
underlying client via monkeypatching. Since the real client would call
the API, we substitute it with an async generator stub.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncIterator

from src.core.interfaces import TriggerEvent, TriggerReason, LLMResponse
from src.llm.openai_provider import (
    OpenAIProvider,
    _SYSTEM_PROMPT as OPENAI_BASE,
    _SYSTEM_PROMPT_EXPLAIN as OPENAI_EXPLAIN,
    _SYSTEM_PROMPT_SILENT as OPENAI_SILENT,
)
from src.llm.claude_provider import (
    ClaudeProvider,
    _SYSTEM_PROMPT as CLAUDE_BASE,
    _SYSTEM_PROMPT_EXPLAIN as CLAUDE_EXPLAIN,
    _SYSTEM_PROMPT_SILENT as CLAUDE_SILENT,
)
from src.profiles.heuristics import CONSERVATIVE_NOTE as _CONSERVATIVE_NOTE

_TRIGGER = TriggerEvent(
    reason=TriggerReason.SILENCE_TIMEOUT,
    context_text="¿Listo?",
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _collected_system_prompt_openai(provider: OpenAIProvider, addon: str, conservative: bool) -> str:
    """Run respond() and capture the system message sent to the client."""
    captured = {}

    async def fake_create(**kwargs):
        captured["system"] = next(
            m["content"] for m in kwargs["messages"] if m["role"] == "system"
        )

        async def empty_stream():
            return
            yield  # pragma: no cover

        # Return an async iterable with choices
        class FakeChunk:
            class delta:
                content = None
            choices = [type("C", (), {"delta": delta})()]

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
        async for _ in provider.respond(
            "context",
            _TRIGGER,
            system_prompt_addon=addon,
            conservative_mode=conservative,
        ):
            pass

    asyncio.run(run())
    return captured["system"]


def _collected_system_prompt_claude(provider: ClaudeProvider, addon: str, conservative: bool) -> str:
    """Run respond() and capture the system kwarg sent to the client."""
    captured = {}

    class FakeStream:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def __aiter__(self):
            return
            yield  # pragma: no cover
        @property
        def text_stream(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
        async def get_final_message(self):
            msg = MagicMock()
            msg.content = []
            return msg

    def fake_stream_ctx(**kwargs):
        captured["system"] = kwargs["system"]
        return FakeStream()

    provider.client = MagicMock()
    provider.client.messages = MagicMock()
    provider.client.messages.stream = MagicMock(side_effect=fake_stream_ctx)

    async def run():
        async for _ in provider.respond(
            "context",
            _TRIGGER,
            system_prompt_addon=addon,
            conservative_mode=conservative,
        ):
            pass

    asyncio.run(run())
    return captured["system"]


# ── OpenAI provider tests ─────────────────────────────────────────────────────

class TestOpenAIProviderPromptComposition:
    def setup_method(self):
        self.provider = OpenAIProvider(api_key="test-key")

    def test_empty_addon_system_prompt_equals_base(self):
        system = _collected_system_prompt_openai(self.provider, addon="", conservative=False)
        assert system == OPENAI_BASE
        assert not system.endswith("\n\n")

    def test_non_empty_addon_appended_verbatim(self):
        addon = "Respondé solo si hay una pregunta real."
        system = _collected_system_prompt_openai(self.provider, addon=addon, conservative=False)
        assert system == OPENAI_BASE + "\n\n" + addon

    def test_conservative_mode_appends_note(self):
        system = _collected_system_prompt_openai(self.provider, addon="", conservative=True)
        assert system == OPENAI_BASE + "\n\n" + _CONSERVATIVE_NOTE

    def test_conservative_mode_false_no_note(self):
        system = _collected_system_prompt_openai(self.provider, addon="", conservative=False)
        assert _CONSERVATIVE_NOTE not in system

    def test_addon_and_conservative_both_appended(self):
        addon = "Solo preguntas directas."
        system = _collected_system_prompt_openai(self.provider, addon=addon, conservative=True)
        assert system == OPENAI_BASE + "\n\n" + addon + "\n\n" + _CONSERVATIVE_NOTE


# ── Claude provider tests ─────────────────────────────────────────────────────

class TestClaudeProviderPromptComposition:
    def setup_method(self):
        self.provider = ClaudeProvider(api_key="test-key")

    def test_empty_addon_system_prompt_equals_base(self):
        system = _collected_system_prompt_claude(self.provider, addon="", conservative=False)
        assert system == CLAUDE_BASE
        assert not system.endswith("\n\n")

    def test_non_empty_addon_appended_verbatim(self):
        addon = "Respondé solo si hay una pregunta real."
        system = _collected_system_prompt_claude(self.provider, addon=addon, conservative=False)
        assert system == CLAUDE_BASE + "\n\n" + addon

    def test_conservative_mode_appends_note(self):
        system = _collected_system_prompt_claude(self.provider, addon="", conservative=True)
        assert system == CLAUDE_BASE + "\n\n" + _CONSERVATIVE_NOTE

    def test_conservative_mode_false_no_note(self):
        system = _collected_system_prompt_claude(self.provider, addon="", conservative=False)
        assert _CONSERVATIVE_NOTE not in system

    def test_addon_and_conservative_both_appended(self):
        addon = "Solo preguntas directas."
        system = _collected_system_prompt_claude(self.provider, addon=addon, conservative=True)
        assert system == CLAUDE_BASE + "\n\n" + addon + "\n\n" + _CONSERVATIVE_NOTE


# ── New: response_mode tests (OpenAI) ────────────────────────────────────────

class TestOpenAIResponseMode:
    def setup_method(self):
        self.provider = OpenAIProvider(api_key="test-key")

    def test_copilot_mode_uses_base_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="copilot")
        assert result.startswith(OPENAI_BASE[:30])

    def test_explain_mode_uses_explain_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="explain")
        assert result.startswith(OPENAI_EXPLAIN[:30])

    def test_silent_mode_uses_silent_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="silent")
        assert result.startswith(OPENAI_SILENT[:30])

    def test_conservative_note_not_appended_for_explain(self):
        result = self.provider._build_system_prompt("", True, response_mode="explain")
        assert _CONSERVATIVE_NOTE not in result

    def test_conservative_note_not_appended_for_silent(self):
        result = self.provider._build_system_prompt("", True, response_mode="silent")
        assert _CONSERVATIVE_NOTE not in result

    def test_explain_mode_different_from_copilot_base(self):
        """Explain prompt must be a different text from the copilot base."""
        assert OPENAI_EXPLAIN != OPENAI_BASE

    def test_silent_mode_different_from_copilot_base(self):
        """Silent prompt must be a different text from the copilot base."""
        assert OPENAI_SILENT != OPENAI_BASE


class TestOpenAIModelOverride:
    def setup_method(self):
        self.provider = OpenAIProvider(api_key="test-key")

    def test_model_override_bypasses_token_logic(self):
        result = self.provider._select_model("text", "hi", model_override="gpt-5.6-terra")
        assert result == "gpt-5.6-terra"

    def test_empty_override_keeps_nano_for_short_context(self):
        result = self.provider._select_model("hi", "hello", model_override="")
        assert result == self.provider.nano_model

    def test_empty_override_keeps_mini_for_long_context(self):
        long = "word " * 600
        result = self.provider._select_model(long, "hi", model_override="")
        assert result == self.provider.mini_model


# ── New: response_mode tests (Claude) ────────────────────────────────────────

class TestClaudeResponseMode:
    def setup_method(self):
        self.provider = ClaudeProvider(api_key="test-key")

    def test_copilot_mode_uses_base_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="copilot")
        assert result.startswith(CLAUDE_BASE[:30])

    def test_explain_mode_uses_explain_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="explain")
        assert result.startswith(CLAUDE_EXPLAIN[:30])

    def test_silent_mode_uses_silent_prompt(self):
        result = self.provider._build_system_prompt("", False, response_mode="silent")
        assert result.startswith(CLAUDE_SILENT[:30])

    def test_conservative_note_not_appended_for_explain(self):
        result = self.provider._build_system_prompt("", True, response_mode="explain")
        assert _CONSERVATIVE_NOTE not in result

    def test_conservative_note_not_appended_for_silent(self):
        result = self.provider._build_system_prompt("", True, response_mode="silent")
        assert _CONSERVATIVE_NOTE not in result

    def test_explain_mode_different_from_copilot_base(self):
        assert CLAUDE_EXPLAIN != CLAUDE_BASE

    def test_silent_mode_different_from_copilot_base(self):
        assert CLAUDE_SILENT != CLAUDE_BASE
