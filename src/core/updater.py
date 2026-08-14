"""
`call-copilot update` — reinstalls the pipx package at the latest commit of
its tracked branch, reusing the same optional-dependency profile install.sh
saved at install time (~/.call-copilot/install-profile) so the user isn't
re-prompted for extras on every update.
"""

import subprocess

from src.core.paths import app_home

_GIT_SPEC = "git+https://github.com/EmaSleal/call-copilot.git@linux-support"


def _profile_path():
    return app_home() / "install-profile"


def read_install_profile() -> str:
    """Comma-separated extras saved at install time, or "" for the minimal
    (no-extras) profile / when nothing was ever saved (e.g. a dev checkout,
    or install.sh wasn't used)."""
    path = _profile_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_pip_spec(extras: str) -> str:
    pkg = f"call-copilot[{extras}]" if extras else "call-copilot"
    return f"{pkg} @ {_GIT_SPEC}"


def run_update() -> int:
    extras = read_install_profile()
    spec = build_pip_spec(extras)
    print(f"Actualizando call-copilot ({extras or 'sin extras'})...")
    try:
        result = subprocess.run(["pipx", "install", "--force", spec])
    except FileNotFoundError:
        print("pipx no está instalado — no se puede actualizar. Volvé a correr install.sh.")
        return 1
    return result.returncode
