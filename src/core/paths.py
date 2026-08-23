"""
Resolves the base directory for all persistent app state (DB, .env,
chroma, whisper-text, video downloads). Zero I/O beyond a filesystem stat
and os.getenv — safe to import from the hot path.

Dev checkouts (git repo present next to the running code) keep the
historical repo-relative layout — no behavior change for the existing
`.venv`/run.sh workflow. Installed packages (pipx, no .git alongside the
code) get `~/.call-copilot/`, so the app works run from any directory.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_dev_checkout() -> bool:
    return (_REPO_ROOT / ".git").exists()


def app_home() -> Path:
    """Base directory for persistent app state. Callers create their own
    subdirectories as needed (mirrors the existing DB_PATH.parent.mkdir()
    convention) — this function does no I/O itself.

    Dev checkouts resolve to the absolute repo root, not a relative
    Path(".") — that used to resolve against the CALLING PROCESS's cwd,
    which happened to match the repo root for every in-repo invocation
    (pytest, `call-copilot` run in place) but silently broke the moment an
    external launcher spawned the process elsewhere (e.g. call-copilot-mcp
    started by an MCP client like Claude Desktop with an unrelated cwd —
    confirmed via a real "unable to open database file" error)."""
    if _is_dev_checkout():
        return _REPO_ROOT
    return Path.home() / ".call-copilot"
