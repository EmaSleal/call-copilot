"""
Unit tests for src/tui/bootstrap.py::_build_stt().

STT_BACKEND is a RESTART-scope setting (config_defaults.RESTART_KEYS):
_preload_models() only builds the WhisperLocalSTT singleton when
whisper_local is already active at app startup, before Textual takes over
the terminal. Switching to whisper_local mid-session (without restarting)
used to fall through to constructing WhisperModel() live, which crashes
with a cryptic `ValueError: bad value(s) in fds_to_keep` — the same tqdm/
Textual file-descriptor collision already fixed for the video pipeline.
_build_stt() must instead fail with a clear, actionable message.
"""

from unittest.mock import MagicMock

import pytest

from src.tui import bootstrap


@pytest.fixture(autouse=True)
def _reset_whisper_singleton(monkeypatch):
    """Isolates the module-level cache between tests."""
    monkeypatch.setattr(bootstrap, "_whisper_stt_instance", None)


class TestBuildSttDeepgram:
    def test_returns_deepgram_provider(self, monkeypatch):
        monkeypatch.setattr(bootstrap.config_defaults, "stt_backend", lambda: "deepgram")
        monkeypatch.setenv("DEEPGRAM_API_KEY", "fake-key")

        from src.stt.deepgram_provider import DeepgramSTT

        result = bootstrap._build_stt()

        assert isinstance(result, DeepgramSTT)


class TestBuildSttWhisperLocal:
    def test_reuses_the_preloaded_singleton(self, monkeypatch):
        monkeypatch.setattr(bootstrap.config_defaults, "stt_backend", lambda: "whisper_local")
        sentinel = MagicMock(name="preloaded-whisper-instance")
        monkeypatch.setattr(bootstrap, "_whisper_stt_instance", sentinel)

        result = bootstrap._build_stt()

        assert result is sentinel

    def test_raises_clear_error_when_not_preloaded(self, monkeypatch):
        """Backend switched to whisper_local without a restart — the
        singleton was never built pre-Textual. Must fail loudly and
        clearly instead of crashing on a live WhisperModel() construction."""
        monkeypatch.setattr(bootstrap.config_defaults, "stt_backend", lambda: "whisper_local")

        with pytest.raises(RuntimeError, match="restart"):
            bootstrap._build_stt()
