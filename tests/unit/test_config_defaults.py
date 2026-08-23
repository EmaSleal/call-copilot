"""
Unit tests for src.core.config_defaults — canonical realtime provider/backend
defaults shared by main.py and src/tui/app.py (Phase 2, PR1 of
config-settings-panel).

Zero-I/O module (pure os.getenv reads) — no mocking required beyond
monkeypatch.setenv/delenv for isolation between tests.
"""

import pytest

from src.core.config_defaults import (
    DEFAULT_LANGUAGE,
    DEFAULT_LLM_BACKEND,
    DEFAULT_STT_BACKEND,
    DEFAULT_WHISPER_MODEL_CALL,
    DEFAULT_WHISPER_MODEL_VIDEO,
    DEFAULT_SILENCE_THRESHOLD_MS,
    WHISPER_SIZES,
    RESTART_KEYS,
    Scope,
    language,
    llm_backend,
    stt_backend,
    whisper_model_call,
    whisper_model_video,
    silence_threshold_ms,
    scope_of,
    tech_scout_db_path,
    mcp_allow_approvals,
    mcp_allow_video_processing,
)


class TestLLMBackendDefault:
    def test_defaults_to_gpt_when_unset(self, monkeypatch):
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        assert llm_backend() == "gpt"
        assert DEFAULT_LLM_BACKEND == "gpt"

    def test_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "")
        assert llm_backend() == DEFAULT_LLM_BACKEND

    def test_honors_explicit_value(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "claude")
        assert llm_backend() == "claude"


class TestSTTBackendDefault:
    def test_defaults_to_deepgram_when_unset(self, monkeypatch):
        monkeypatch.delenv("STT_BACKEND", raising=False)
        assert stt_backend() == "deepgram"
        assert DEFAULT_STT_BACKEND == "deepgram"

    def test_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("STT_BACKEND", "")
        assert stt_backend() == DEFAULT_STT_BACKEND

    def test_honors_explicit_value(self, monkeypatch):
        monkeypatch.setenv("STT_BACKEND", "whisper_local")
        assert stt_backend() == "whisper_local"


class TestWhisperModelCall:
    def test_defaults_to_large_v3_turbo_when_unset(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL_CALL", raising=False)
        monkeypatch.delenv("WHISPER_MODEL", raising=False)
        assert whisper_model_call() == "large-v3-turbo"
        assert DEFAULT_WHISPER_MODEL_CALL == "large-v3-turbo"

    def test_falls_back_to_legacy_whisper_model(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL_CALL", raising=False)
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_call() == "medium"

    def test_new_var_wins_over_legacy(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_CALL", "small")
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_call() == "small"

    def test_empty_new_var_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_CALL", "")
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_call() == "medium"

    def test_empty_on_both_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_CALL", "")
        monkeypatch.setenv("WHISPER_MODEL", "")
        assert whisper_model_call() == DEFAULT_WHISPER_MODEL_CALL


class TestWhisperModelVideo:
    def test_defaults_to_base_when_unset(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL_VIDEO", raising=False)
        monkeypatch.delenv("WHISPER_MODEL", raising=False)
        assert whisper_model_video() == "base"
        assert DEFAULT_WHISPER_MODEL_VIDEO == "base"

    def test_falls_back_to_legacy_whisper_model(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MODEL_VIDEO", raising=False)
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_video() == "medium"

    def test_new_var_wins_over_legacy(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_VIDEO", "tiny")
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_video() == "tiny"

    def test_empty_new_var_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL_VIDEO", "")
        monkeypatch.setenv("WHISPER_MODEL", "medium")
        assert whisper_model_video() == "medium"


class TestSilenceThresholdMs:
    def test_defaults_to_2000_when_unset(self, monkeypatch):
        monkeypatch.delenv("SILENCE_THRESHOLD_MS", raising=False)
        assert silence_threshold_ms() == 2000
        assert DEFAULT_SILENCE_THRESHOLD_MS == 2000

    def test_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("SILENCE_THRESHOLD_MS", "")
        assert silence_threshold_ms() == DEFAULT_SILENCE_THRESHOLD_MS

    def test_honors_explicit_value(self, monkeypatch):
        monkeypatch.setenv("SILENCE_THRESHOLD_MS", "1500")
        assert silence_threshold_ms() == 1500

    def test_non_numeric_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SILENCE_THRESHOLD_MS", "not-a-number")
        assert silence_threshold_ms() == DEFAULT_SILENCE_THRESHOLD_MS


class TestWhisperSizes:
    def test_contains_expected_sizes(self):
        assert WHISPER_SIZES == (
            "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo",
        )

    def test_defaults_are_valid_sizes(self):
        assert DEFAULT_WHISPER_MODEL_CALL in WHISPER_SIZES
        assert DEFAULT_WHISPER_MODEL_VIDEO in WHISPER_SIZES


class TestScopeOf:
    @pytest.mark.parametrize("key,expected", [
        ("STT_BACKEND", Scope.RESTART),
        ("WHISPER_MODEL_CALL", Scope.RESTART),
        ("WHISPER_MODEL_VIDEO", Scope.NEXT_VIDEO),
        ("SILENCE_THRESHOLD_MS", Scope.RESTART),
        ("LLM_BACKEND", Scope.NEXT_CALL),
        ("OPENAI_API_KEY", Scope.NEXT_CALL),
        ("ANTHROPIC_API_KEY", Scope.NEXT_CALL),
        ("DEEPGRAM_API_KEY", Scope.NEXT_CALL),
    ])
    def test_scope_table(self, key, expected):
        assert scope_of(key) == expected

    def test_unknown_key_defaults_to_next_call(self):
        assert scope_of("SOME_UNKNOWN_KEY") == Scope.NEXT_CALL

    def test_restart_keys_matches_scope_table(self):
        # RESTART_KEYS is a convenience set mirroring the "restart" rows of
        # scope_of()'s table — keep them in sync.
        assert RESTART_KEYS == {"STT_BACKEND", "WHISPER_MODEL_CALL", "SILENCE_THRESHOLD_MS"}
        for key in RESTART_KEYS:
            assert scope_of(key) == Scope.RESTART

    @pytest.mark.parametrize("key", ["MCP_ALLOW_APPROVALS", "MCP_ALLOW_VIDEO_PROCESSING"])
    def test_mcp_write_flags_map_to_mcp_restart_scope(self, key):
        # A distinct scope from RESTART: restarting the TUI does nothing
        # for these — the process that needs restarting is the external
        # MCP client (e.g. Claude Desktop), which the TUI doesn't control.
        assert scope_of(key) == Scope.MCP_RESTART


class TestLanguage:
    def test_defaults_to_en_when_unset(self, monkeypatch):
        monkeypatch.delenv("LANGUAGE", raising=False)
        assert language() == "en"
        assert DEFAULT_LANGUAGE == "en"

    def test_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "")
        assert language() == DEFAULT_LANGUAGE

    def test_honors_explicit_value(self, monkeypatch):
        monkeypatch.setenv("LANGUAGE", "es")
        assert language() == "es"


class TestTechScoutDbPath:
    def test_defaults_to_hermes_layout_when_unset(self, monkeypatch):
        monkeypatch.delenv("TECH_SCOUT_DB_PATH", raising=False)
        assert tech_scout_db_path().endswith(".hermes/tech-scout/tools.db")

    def test_empty_string_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("TECH_SCOUT_DB_PATH", "")
        assert tech_scout_db_path().endswith(".hermes/tech-scout/tools.db")

    def test_honors_explicit_value(self, monkeypatch):
        monkeypatch.setenv("TECH_SCOUT_DB_PATH", "/custom/path/tools.db")
        assert tech_scout_db_path() == "/custom/path/tools.db"


class TestMcpAllowApprovals:
    def test_defaults_to_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_APPROVALS", raising=False)
        assert mcp_allow_approvals() is False

    def test_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_APPROVALS", "True")
        assert mcp_allow_approvals() is True

    def test_any_other_value_is_false(self, monkeypatch):
        # Same strict parsing as src/mcp/server.py's own gate — only the
        # literal "true" (case-insensitive) enables it.
        monkeypatch.setenv("MCP_ALLOW_APPROVALS", "1")
        assert mcp_allow_approvals() is False


class TestMcpAllowVideoProcessing:
    def test_defaults_to_false_when_unset(self, monkeypatch):
        monkeypatch.delenv("MCP_ALLOW_VIDEO_PROCESSING", raising=False)
        assert mcp_allow_video_processing() is False

    def test_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_VIDEO_PROCESSING", "TRUE")
        assert mcp_allow_video_processing() is True

    def test_any_other_value_is_false(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_VIDEO_PROCESSING", "1")
        assert mcp_allow_video_processing() is False


class TestProviderWiring:
    """
    Phase 4: main.py's build_stt_provider/build_llm_provider and
    src.tui.bootstrap's _build_stt/_build_llm must resolve backends via
    config_defaults getters, and agree with each other when no .env
    override is present (both land on the "gpt" realtime default).
    """

    def test_main_and_app_agree_on_llm_backend_with_no_override(self, monkeypatch):
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        import main
        import src.tui.bootstrap as bootstrap

        llm_main = main.build_llm_provider()
        llm_app = bootstrap._build_llm()
        assert type(llm_main).__name__ == "OpenAIProvider"
        assert type(llm_app).__name__ == "OpenAIProvider"

    def test_main_and_app_agree_on_stt_backend_with_no_override(self, monkeypatch):
        monkeypatch.delenv("STT_BACKEND", raising=False)
        monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
        import main
        import src.tui.bootstrap as bootstrap

        stt_main = main.build_stt_provider()
        stt_app = bootstrap._build_stt()
        assert type(stt_main).__name__ == "DeepgramSTT"
        assert type(stt_app).__name__ == "DeepgramSTT"
