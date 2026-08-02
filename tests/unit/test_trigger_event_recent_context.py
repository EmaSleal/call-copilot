"""
Unit tests for TriggerEvent.recent_context field.
RED phase: TriggerEvent does not yet have this field.
"""

import pytest
from src.core.interfaces import TriggerEvent, TriggerReason


class TestTriggerEventRecentContext:
    def test_recent_context_defaults_to_empty_string(self):
        """TriggerEvent can be created without recent_context — defaults to ''."""
        event = TriggerEvent(
            reason=TriggerReason.SILENCE_TIMEOUT,
            context_text="some text",
        )
        assert event.recent_context == ""

    def test_recent_context_can_be_set(self):
        """TriggerEvent accepts a non-empty recent_context."""
        text = "word1 word2 word3"
        event = TriggerEvent(
            reason=TriggerReason.SILENCE_TIMEOUT,
            context_text="some text",
            recent_context=text,
        )
        assert event.recent_context == text

    def test_existing_callers_not_broken(self):
        """Creating TriggerEvent with only required fields still works."""
        event = TriggerEvent(
            reason=TriggerReason.QUESTION_DETECTED,
            context_text="¿Cómo funciona OAuth?",
            confidence=0.9,
        )
        assert event.recent_context == ""
        assert event.confidence == 0.9
