"""
Unit tests for src.core.paths — resolves the base directory for all
persistent app state (DB, .env, chroma, whisper-text, video downloads).

Dev checkouts (git repo present next to the running code) resolve to the
repo root as an ABSOLUTE path — not the process's current working
directory. A relative Path(".") happened to be equivalent for every
in-repo invocation (pytest, `call-copilot` run from the repo dir), but
broke the moment an external launcher spawns the process with a
different cwd — e.g. `call-copilot-mcp` launched by an MCP client like
Claude Desktop, which does NOT run it from the repo directory, and hit a
real "unable to open database file" error because of this. Installed
packages (pipx, no .git alongside the code) get `~/.call-copilot/` so the
app works run from any directory — same reasoning, just already correct
there since it was already absolute.
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
    def test_dev_checkout_returns_the_absolute_repo_root(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        assert app_home() == tmp_path

    def test_dev_checkout_is_independent_of_cwd(self, tmp_path, monkeypatch):
        """Regression: app_home() used to return a relative Path(".") in
        dev checkouts, which resolved against the CALLING PROCESS's cwd
        instead of the repo root. That happened to match for every
        in-repo invocation (pytest, `call-copilot` run from the repo dir)
        but broke for a process launched with a different cwd — e.g.
        call-copilot-mcp spawned by an external MCP client, which hit a
        real "unable to open database file" error because of this."""
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        monkeypatch.chdir(Path("/"))
        assert app_home() == tmp_path

    def test_installed_returns_user_home_call_copilot(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "fake-home")
        assert app_home() == tmp_path / "fake-home" / ".call-copilot"

    def test_dev_path_matches_historical_default_when_run_from_repo_root(self, tmp_path, monkeypatch):
        """app_home() / "data" / "app.db" must still resolve to the same
        real file as the old literal Path("data/app.db") default when the
        process IS launched from the repo root (the historical/normal dev
        workflow: pytest, `call-copilot` run in-place) — only the
        representation (absolute vs relative) changed, not the target."""
        (tmp_path / ".git").mkdir()
        monkeypatch.setattr("src.core.paths._REPO_ROOT", tmp_path)
        monkeypatch.chdir(tmp_path)
        assert app_home() / "data" / "app.db" == (tmp_path / "data" / "app.db")
        assert (app_home() / "data" / "app.db").resolve() == Path("data/app.db").resolve()
