"""
Unit tests for SettingsScreen's pure helpers (Phase 5, PR1 of
config-settings-panel).

Textual cannot boot headlessly (see tests/unit/test_profile_manager_screen.py),
so — following this repo's established convention — the validation/diff/
scope-summary logic that SettingsScreen's save handler delegates to lives as
module-level pure functions in src/tui/app.py, importable and testable
directly without mounting any widget.
"""

import pytest

from src.tui.screens.settings import (
    validate_settings_form, diff_changed_keys, summarize_scopes, key_to_provider,
    format_sync_feedback, key_placeholder,
)
from src.core.config_defaults import WHISPER_SIZES

# `english`/`spanish` fixtures come from tests/conftest.py (shared across
# every migrated TUI module's tests).


# ---------------------------------------------------------------------------
# validate_settings_form()
# ---------------------------------------------------------------------------

class TestValidateSettingsForm:
    def test_valid_whisper_sizes_pass(self):
        values = {"WHISPER_MODEL_CALL": "large-v3-turbo", "WHISPER_MODEL_VIDEO": "base"}
        assert validate_settings_form(values) == []

    def test_invalid_whisper_model_call_is_rejected(self):
        values = {"WHISPER_MODEL_CALL": "not-a-real-size"}
        errors = validate_settings_form(values)
        assert len(errors) == 1
        assert "WHISPER_MODEL_CALL" in errors[0]

    def test_invalid_whisper_model_video_is_rejected(self):
        values = {"WHISPER_MODEL_VIDEO": "gigantic"}
        errors = validate_settings_form(values)
        assert len(errors) == 1
        assert "WHISPER_MODEL_VIDEO" in errors[0]

    def test_both_invalid_reports_two_errors(self):
        values = {"WHISPER_MODEL_CALL": "bogus", "WHISPER_MODEL_VIDEO": "also-bogus"}
        assert len(validate_settings_form(values)) == 2

    def test_empty_whisper_value_is_not_rejected(self):
        assert validate_settings_form({"WHISPER_MODEL_CALL": ""}) == []

    def test_missing_key_is_not_rejected(self):
        assert validate_settings_form({}) == []

    @pytest.mark.parametrize("size", WHISPER_SIZES)
    def test_every_known_size_is_accepted(self, size):
        values = {"WHISPER_MODEL_CALL": size, "WHISPER_MODEL_VIDEO": size}
        assert validate_settings_form(values) == []

    def test_valid_silence_threshold_passes(self):
        assert validate_settings_form({"SILENCE_THRESHOLD_MS": "2000"}) == []

    def test_non_numeric_silence_threshold_is_rejected(self):
        errors = validate_settings_form({"SILENCE_THRESHOLD_MS": "abc"})
        assert len(errors) == 1
        assert "SILENCE_THRESHOLD_MS" in errors[0]

    def test_silence_threshold_below_range_is_rejected(self):
        errors = validate_settings_form({"SILENCE_THRESHOLD_MS": "50"})
        assert len(errors) == 1

    def test_silence_threshold_above_range_is_rejected(self):
        errors = validate_settings_form({"SILENCE_THRESHOLD_MS": "9000"})
        assert len(errors) == 1

    def test_silence_threshold_boundaries_are_accepted(self):
        assert validate_settings_form({"SILENCE_THRESHOLD_MS": "100"}) == []
        assert validate_settings_form({"SILENCE_THRESHOLD_MS": "5000"}) == []

    def test_empty_silence_threshold_is_not_rejected(self):
        assert validate_settings_form({"SILENCE_THRESHOLD_MS": ""}) == []


# ---------------------------------------------------------------------------
# diff_changed_keys()
# ---------------------------------------------------------------------------

class TestDiffChangedKeys:
    def test_no_changes_returns_empty_dict(self):
        original = {"LLM_BACKEND": "gpt"}
        assert diff_changed_keys(original, {"LLM_BACKEND": "gpt"}) == {}

    def test_changed_key_is_returned(self):
        original = {"LLM_BACKEND": "gpt"}
        new = {"LLM_BACKEND": "claude"}
        assert diff_changed_keys(original, new) == {"LLM_BACKEND": "claude"}

    def test_unchanged_key_is_excluded_alongside_changed_key(self):
        original = {"LLM_BACKEND": "gpt", "STT_BACKEND": "deepgram"}
        new = {"LLM_BACKEND": "claude", "STT_BACKEND": "deepgram"}
        assert diff_changed_keys(original, new) == {"LLM_BACKEND": "claude"}

    def test_new_key_not_in_original_counts_as_changed(self):
        assert diff_changed_keys({}, {"OPENAI_API_KEY": "sk-x"}) == {"OPENAI_API_KEY": "sk-x"}

    def test_empty_new_dict_returns_empty(self):
        assert diff_changed_keys({"LLM_BACKEND": "gpt"}, {}) == {}


# ---------------------------------------------------------------------------
# summarize_scopes()
# ---------------------------------------------------------------------------

class TestSummarizeScopes:
    def test_stt_backend_maps_to_restart_badge(self, spanish):
        result = summarize_scopes(["STT_BACKEND"])
        assert "reiniciar" in result["STT_BACKEND"]

    def test_whisper_model_call_maps_to_restart_badge(self, spanish):
        result = summarize_scopes(["WHISPER_MODEL_CALL"])
        assert "reiniciar" in result["WHISPER_MODEL_CALL"]

    def test_whisper_model_video_maps_to_next_video_badge_not_restart(self, spanish):
        result = summarize_scopes(["WHISPER_MODEL_VIDEO"])
        assert "reiniciar" not in result["WHISPER_MODEL_VIDEO"]
        assert "video" in result["WHISPER_MODEL_VIDEO"]

    def test_silence_threshold_maps_to_restart_badge(self, spanish):
        result = summarize_scopes(["SILENCE_THRESHOLD_MS"])
        assert "reiniciar" in result["SILENCE_THRESHOLD_MS"]

    def test_llm_backend_maps_to_next_call_badge(self, spanish):
        result = summarize_scopes(["LLM_BACKEND"])
        assert "llamada" in result["LLM_BACKEND"]
        assert "reiniciar" not in result["LLM_BACKEND"]

    def test_api_key_maps_to_next_call_badge(self, spanish):
        result = summarize_scopes(["OPENAI_API_KEY"])
        assert "llamada" in result["OPENAI_API_KEY"]

    def test_empty_changed_keys_returns_empty_dict(self):
        assert summarize_scopes([]) == {}

    def test_multiple_keys_each_get_their_own_badge(self):
        result = summarize_scopes(["STT_BACKEND", "LLM_BACKEND"])
        assert set(result.keys()) == {"STT_BACKEND", "LLM_BACKEND"}


# ---------------------------------------------------------------------------
# key_to_provider() — PR2: maps a saved API-key env var to the model_catalog
# provider whose cache must be invalidated (design decision 6).
# ---------------------------------------------------------------------------

class TestKeyToProvider:
    def test_openai_key_maps_to_gpt(self):
        assert key_to_provider("OPENAI_API_KEY") == "gpt"

    def test_anthropic_key_maps_to_claude(self):
        assert key_to_provider("ANTHROPIC_API_KEY") == "claude"

    def test_deepgram_key_has_no_catalog_provider(self):
        assert key_to_provider("DEEPGRAM_API_KEY") is None

    def test_unrelated_key_has_no_catalog_provider(self):
        assert key_to_provider("LLM_BACKEND") is None


# ---------------------------------------------------------------------------
# format_sync_feedback() — "Sincronizar tech-scout" button feedback text
# ---------------------------------------------------------------------------

class TestFormatSyncFeedback:
    def test_reports_imported_and_skipped_counts(self):
        msg = format_sync_feedback(3, 1)
        assert "3" in msg
        assert "1" in msg

    def test_zero_imported_and_zero_skipped_still_reports_success(self):
        msg = format_sync_feedback(0, 0)
        assert "0" in msg


# ---------------------------------------------------------------------------
# key_placeholder() — masked/empty placeholder for API key Inputs
# ---------------------------------------------------------------------------

class TestKeyPlaceholder:
    def test_masked_when_env_var_set(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-something")
        assert "configur" in key_placeholder("OPENAI_API_KEY")

    def test_not_configured_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert key_placeholder("OPENAI_API_KEY") != ""


# ---------------------------------------------------------------------------
# i18n-hot-swap-tui — same pure functions, asserted in English via t()
# ---------------------------------------------------------------------------

class TestValidateSettingsFormEnglish:
    def test_invalid_whisper_model_call_message_in_english(self, english):
        errors = validate_settings_form({"WHISPER_MODEL_CALL": "not-a-real-size"})
        assert "invalid" in errors[0]
        assert "WHISPER_MODEL_CALL" in errors[0]

    def test_non_numeric_silence_threshold_message_in_english(self, english):
        errors = validate_settings_form({"SILENCE_THRESHOLD_MS": "abc"})
        assert "must be an integer" in errors[0]

    def test_silence_threshold_out_of_range_message_in_english(self, english):
        errors = validate_settings_form({"SILENCE_THRESHOLD_MS": "50"})
        assert "must be between" in errors[0]


class TestSummarizeScopesEnglish:
    def test_stt_backend_maps_to_restart_badge(self, english):
        result = summarize_scopes(["STT_BACKEND"])
        assert "restart" in result["STT_BACKEND"]

    def test_whisper_model_video_maps_to_next_video_badge_not_restart(self, english):
        result = summarize_scopes(["WHISPER_MODEL_VIDEO"])
        assert "restart" not in result["WHISPER_MODEL_VIDEO"]
        assert "video" in result["WHISPER_MODEL_VIDEO"]

    def test_llm_backend_maps_to_next_call_badge(self, english):
        result = summarize_scopes(["LLM_BACKEND"])
        assert "call" in result["LLM_BACKEND"]
        assert "restart" not in result["LLM_BACKEND"]


class TestFormatSyncFeedbackEnglish:
    def test_reports_imported_and_skipped_counts(self, english):
        msg = format_sync_feedback(3, 1)
        assert "Synced" in msg
        assert "3" in msg
        assert "1" in msg
