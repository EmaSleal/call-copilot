"""
Unit tests for src.core.paths — resolves the base directory for all
persistent app state (DB, .env, chroma, whisper-text, video downloads).

Dev checkouts (git repo present next to the running code) keep the
historical repo-relative layout (`Path(".")`) — zero behavior change for
the existing development workflow. Installed packages (pipx, no .git
alongside the code) get `~/.call-copilot/` so the app works run from any
directory.
"""

from pathlib import Path

from src.core.paths import _is_dev_checkout, app_home


class TestIsDevCheckout:
    def test_true_when_dot_git_exists(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        assert _is_dev_checkout() is True

    def test_false_when_dot_git_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        assert _is_dev_checkout() is False


class TestAppHome:
    def test_dev_checkout_returns_relative_dot(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        assert app_home() == Path(".")

    def test_installed_returns_user_home_call_copilot(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake-home")
        assert app_home() == tmp_path / "fake-home" / ".call-copilot"

    def test_dev_relative_path_matches_historical_default(self, tmp_path, monkeypatch):
        """app_home() / "data" / "app.db" must render identically to the
        old literal Path("data/app.db") default during dev/test runs —
        pathlib drops the leading "./" on join, so this must hold exactly."""
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        assert app_home() / "data" / "app.db" == Path("data/app.db")
