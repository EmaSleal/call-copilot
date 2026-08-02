"""
Unit tests for profile data models and TriggerEvent extension.
"""

import pytest
from src.core.interfaces import TriggerEvent, TriggerReason
from src.profiles.models import (
    CallProfile,
    ProfileHeuristics,
    ResponseMode,
    AVAILABLE_MODELS,
)


class TestTriggerEventConservativeMode:
    def test_conservative_mode_defaults_to_false(self):
        event = TriggerEvent(
            reason=TriggerReason.SILENCE_TIMEOUT,
            context_text="some text",
        )
        assert event.conservative_mode is False

    def test_conservative_mode_can_be_set_true(self):
        event = TriggerEvent(
            reason=TriggerReason.SILENCE_TIMEOUT,
            context_text="some text",
            conservative_mode=True,
        )
        assert event.conservative_mode is True


class TestCallProfileDefaults:
    def test_system_prompt_addon_defaults_to_empty_string(self):
        profile = CallProfile(
            id="test",
            name="Test",
            description="A test profile",
        )
        assert profile.system_prompt_addon == ""

    def test_heuristics_defaults_to_empty_profile_heuristics(self):
        profile = CallProfile(
            id="test",
            name="Test",
            description="A test profile",
        )
        assert isinstance(profile.heuristics, ProfileHeuristics)
        assert profile.heuristics.discourse_markers == []
        assert profile.heuristics.require_real_question is False

    def test_profile_heuristics_discourse_markers_default_empty(self):
        h = ProfileHeuristics()
        assert h.discourse_markers == []

    def test_profile_heuristics_require_real_question_default_false(self):
        h = ProfileHeuristics()
        assert h.require_real_question is False

    def test_two_profiles_heuristics_are_independent(self):
        """Mutable default guard: each instance must have its own list."""
        p1 = CallProfile(id="a", name="A", description="")
        p2 = CallProfile(id="b", name="B", description="")
        p1.heuristics.discourse_markers.append("¿Sí?")
        assert p2.heuristics.discourse_markers == []


class TestResponseModeEnum:
    def test_has_copilot_value(self):
        assert ResponseMode.copilot.value == "copilot"

    def test_has_explain_value(self):
        assert ResponseMode.explain.value == "explain"

    def test_has_silent_value(self):
        assert ResponseMode.silent.value == "silent"

    def test_is_str_enum(self):
        """ResponseMode must be a str enum so JSON serialization works."""
        assert isinstance(ResponseMode.copilot, str)
        assert ResponseMode.copilot == "copilot"

    def test_can_construct_from_string(self):
        assert ResponseMode("explain") is ResponseMode.explain


class TestAvailableModels:
    def test_available_models_is_list(self):
        assert isinstance(AVAILABLE_MODELS, list)

    def test_available_models_has_at_least_one_entry(self):
        assert len(AVAILABLE_MODELS) >= 1

    def test_each_entry_is_two_strings(self):
        for model_id, label in AVAILABLE_MODELS:
            assert isinstance(model_id, str)
            assert isinstance(label, str)

    def test_empty_string_entry_exists_as_default(self):
        """The '' id means 'use pipeline default logic'."""
        ids = [model_id for model_id, _ in AVAILABLE_MODELS]
        assert "" in ids

    def test_known_model_ids_present(self):
        ids = {model_id for model_id, _ in AVAILABLE_MODELS}
        assert "gpt-5.4-mini" in ids
        assert "gpt-5.4-nano" in ids


class TestCallProfileNewFields:
    def test_response_mode_defaults_to_copilot(self):
        profile = CallProfile(id="x", name="X", description="")
        assert profile.response_mode == ResponseMode.copilot

    def test_model_defaults_to_empty_string(self):
        profile = CallProfile(id="x", name="X", description="")
        assert profile.model == ""

    def test_response_mode_can_be_set_to_explain(self):
        profile = CallProfile(id="x", name="X", description="", response_mode=ResponseMode.explain)
        assert profile.response_mode == ResponseMode.explain

    def test_response_mode_can_be_set_to_silent(self):
        profile = CallProfile(id="x", name="X", description="", response_mode=ResponseMode.silent)
        assert profile.response_mode == ResponseMode.silent

    def test_model_can_be_set_to_non_empty_string(self):
        profile = CallProfile(id="x", name="X", description="", model="gpt-5.4-mini")
        assert profile.model == "gpt-5.4-mini"

    def test_two_profiles_response_modes_are_independent(self):
        p1 = CallProfile(id="a", name="A", description="", response_mode=ResponseMode.silent)
        p2 = CallProfile(id="b", name="B", description="")
        assert p1.response_mode == ResponseMode.silent
        assert p2.response_mode == ResponseMode.copilot
