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
    convention) — this function does no I/O itself."""
    if _is_dev_checkout():
        return Path(".")
    return Path.home() / ".call-copilot"
