"""
Unit tests for src.core.env_store — the only writer of .env (Phase 3, PR1 of
config-settings-panel).

tests/conftest.py mocks `dotenv` globally so the rest of the test suite can
import Textual/app.py modules without installing every heavy production
dependency. env_store needs the REAL python-dotenv package to verify actual
file round-trips (comment preservation, quoting, file mode), so this module
restores the real import before importing env_store for the first time in
the session.
"""

import os
import stat
import sys
from unittest.mock import MagicMock

import pytest

if isinstance(sys.modules.get("dotenv"), MagicMock):
    del sys.modules["dotenv"]
import dotenv  # noqa: E402  (must be the real package before env_store imports it)

from src.core import env_store  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def env_path(tmp_path):
    return tmp_path / ".env"


@pytest.fixture
def example_path(tmp_path):
    path = tmp_path / "example.env"
    path.write_text(
        "# comentario inicial\n"
        "LLM_BACKEND=gpt\n"
        "STT_BACKEND=deepgram\n"
    )
    return path


# ---------------------------------------------------------------------------
# ensure_env_file()
# ---------------------------------------------------------------------------

class TestEnsureEnvFile:
    def test_seeds_from_example_when_env_missing(self, env_path, example_path):
        assert not env_path.exists()
        env_store.ensure_env_file(env_path, example_path)
        assert env_path.exists()
        assert env_path.read_text() == example_path.read_text()

    def test_noop_when_env_already_exists(self, env_path, example_path):
        env_path.write_text("LLM_BACKEND=claude\n")
        env_store.ensure_env_file(env_path, example_path)
        assert env_path.read_text() == "LLM_BACKEND=claude\n"

    def test_creates_empty_file_when_example_also_missing(self, tmp_path):
        target = tmp_path / ".env"
        missing_example = tmp_path / "does_not_exist.env"
        env_store.ensure_env_file(target, missing_example)
        assert target.exists()

    def test_sets_file_mode_0600(self, env_path, example_path):
        env_store.ensure_env_file(env_path, example_path)
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600

    def test_does_not_touch_mode_of_preexisting_file(self, env_path, example_path):
        env_path.write_text("LLM_BACKEND=claude\n")
        env_path.chmod(0o644)
        env_store.ensure_env_file(env_path, example_path)
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o644


# ---------------------------------------------------------------------------
# write_values()
# ---------------------------------------------------------------------------

class TestWriteValues:
    def test_seeds_env_when_missing_before_write(self, env_path, example_path, monkeypatch):
        monkeypatch.setattr(env_store, "EXAMPLE_ENV_PATH", example_path)
        env_store.write_values({"LLM_BACKEND": "claude"}, env_path=env_path)
        assert env_path.exists()

    def test_writes_new_value(self, env_path):
        env_path.write_text("LLM_BACKEND=gpt\n")
        env_store.write_values({"LLM_BACKEND": "claude"}, env_path=env_path)
        values = dotenv.dotenv_values(str(env_path))
        assert values["LLM_BACKEND"] == "claude"

    def test_preserves_comments_and_unrelated_lines(self, env_path):
        env_path.write_text("# a comment\nLLM_BACKEND=gpt\nSTT_BACKEND=deepgram\n")
        env_store.write_values({"LLM_BACKEND": "claude"}, env_path=env_path)
        content = env_path.read_text()
        assert "# a comment" in content
        assert "STT_BACKEND=deepgram" in content

    def test_value_with_hash_and_spaces_round_trips(self, env_path):
        env_path.write_text("OPENAI_API_KEY=old\n")
        tricky = "sk-test #not-a-comment with spaces"
        env_store.write_values({"OPENAI_API_KEY": tricky}, env_path=env_path)
        values = dotenv.dotenv_values(str(env_path))
        assert values["OPENAI_API_KEY"] == tricky

    def test_empty_values_dict_does_not_touch_file(self, env_path):
        env_path.write_text("LLM_BACKEND=gpt\nSTT_BACKEND=deepgram\n")
        before = env_path.read_text()
        env_store.write_values({}, env_path=env_path)
        assert env_path.read_text() == before

    def test_unchanged_key_line_is_not_rewritten(self, env_path):
        env_path.write_text("LLM_BACKEND=gpt\nSTT_BACKEND=deepgram\n")
        before = env_path.read_text()
        # Same value as what's already on disk — must not reformat the line
        # (dotenv.set_key would otherwise rewrite LLM_BACKEND=gpt as
        # LLM_BACKEND='gpt' even though nothing actually changed).
        env_store.write_values({"LLM_BACKEND": "gpt"}, env_path=env_path)
        assert env_path.read_text() == before

    def test_only_changed_key_line_is_rewritten(self, env_path):
        env_path.write_text("LLM_BACKEND=gpt\nSTT_BACKEND=deepgram\n")
        env_store.write_values(
            {"LLM_BACKEND": "gpt", "STT_BACKEND": "whisper_local"}, env_path=env_path
        )
        values = dotenv.dotenv_values(str(env_path))
        assert values["STT_BACKEND"] == "whisper_local"
        assert values["LLM_BACKEND"] == "gpt"

    def test_file_mode_stays_0600_after_write(self, env_path):
        env_path.write_text("LLM_BACKEND=gpt\n")
        env_path.chmod(0o600)
        env_store.write_values({"LLM_BACKEND": "claude"}, env_path=env_path)
        mode = stat.S_IMODE(env_path.stat().st_mode)
        assert mode == 0o600

    def test_refreshes_in_memory_environment(self, env_path, monkeypatch):
        env_path.write_text("LLM_BACKEND=gpt\n")
        monkeypatch.delenv("LLM_BACKEND", raising=False)
        env_store.write_values({"LLM_BACKEND": "claude"}, env_path=env_path)
        assert os.environ.get("LLM_BACKEND") == "claude"
