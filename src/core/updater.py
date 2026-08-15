"""
call-copilot package-lifecycle commands: update, check-update, version,
uninstall, doctor. Dispatched from src/core/cli.py.
"""

import importlib.metadata
import importlib.util
import shutil
import subprocess
from pathlib import Path

from src.core.paths import _is_dev_checkout, _REPO_ROOT, app_home

_REPO_URL = "https://github.com/EmaSleal/call-copilot.git"
# Fallback ref when no release tag exists yet (e.g. before the first
# release-please PR is ever merged) or the tag lookup fails outright —
# install/update still work, just tracking main's moving HEAD instead of
# a pinned, reproducible release.
_FALLBACK_REF = "main"


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


def get_latest_release_tag() -> str:
    """Latest vX.Y.Z release tag on the public repo (release-please's tag
    format), highest-semver first via `git ls-remote --sort`. Falls back
    to _FALLBACK_REF when no tags exist yet or the query fails — same
    no-token, git-is-already-required approach as get_remote_commit()."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", "--sort=-v:refname", _REPO_URL, "v*"],
            capture_output=True, text=True, check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return _FALLBACK_REF
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not first_line or "refs/tags/" not in first_line:
        return _FALLBACK_REF
    return first_line.rsplit("refs/tags/", 1)[-1]


def build_pip_spec(extras: str, ref: str) -> str:
    pkg = f"call-copilot[{extras}]" if extras else "call-copilot"
    return f"{pkg} @ git+{_REPO_URL}@{ref}"


def get_installed_commit() -> str | None:
    """Full commit SHA of the running code: `git rev-parse HEAD` in a dev
    checkout, or the installed package's PEP 610 direct_url.json commit_id
    otherwise (verified for real against pipx 1.15.0's actual on-disk
    shape). None if neither is determinable."""
    if _is_dev_checkout():
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(_REPO_ROOT), capture_output=True, text=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        return result.stdout.strip()

    try:
        dist = importlib.metadata.distribution("call-copilot")
        return dist.origin.vcs_info.commit_id
    except (importlib.metadata.PackageNotFoundError, AttributeError):
        return None


def get_remote_commit(ref: str = _FALLBACK_REF) -> str | None:
    """Commit SHA the given ref (tag or branch) of the public repo points
    at, via `git ls-remote` — no API token/auth complexity, git is
    guaranteed present (pipx needs it to install from a git URL in the
    first place)."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", _REPO_URL, ref],
            capture_output=True, text=True, check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    line = result.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def _pipx_venvs_dir() -> Path | None:
    """Where pipx keeps its per-package venvs, straight from pipx itself
    (portable across Windows/macOS/Linux — no hardcoded platform path)."""
    try:
        result = subprocess.run(
            ["pipx", "environment", "--value", "PIPX_LOCAL_VENVS"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return Path(value) if value else None


def run_update() -> int:
    """Uninstall-then-install rather than `pipx install --force` — pipx's
    uv-backed venv creation refuses to clear a venv from a prior session,
    so --force fails outright on some setups. `pipx uninstall` on a
    not-yet-installed package returns nonzero; that's expected on a first
    run and must not block the install that follows.

    On Windows, antivirus/real-time scanning can transiently lock files
    mid-uninstall, leaving a half-deleted venv that then makes the
    following install fail ("already seems to be installed") even though
    pipx reported the uninstall as successful. When that happens, force-
    delete the leftover venv directory ourselves and retry the install
    once — same fix a human would do by hand, automated.
    """
    extras = read_install_profile()
    ref = get_latest_release_tag()
    spec = build_pip_spec(extras, ref)
    print(f"Actualizando call-copilot a {ref} ({extras or 'sin extras'})...")
    try:
        subprocess.run(["pipx", "uninstall", "call-copilot"])
        result = subprocess.run(["pipx", "install", spec])
    except FileNotFoundError:
        print("pipx no está instalado — no se puede actualizar. Volvé a correr install.sh.")
        return 1

    if result.returncode != 0:
        venvs_dir = _pipx_venvs_dir()
        if venvs_dir is not None:
            print("La instalación falló — puede haber quedado un venv viejo trabado "
                  "(permisos/antivirus). Lo limpio y reintento una vez...")
            shutil.rmtree(venvs_dir / "call-copilot", ignore_errors=True)
            result = subprocess.run(["pipx", "install", spec])

    return result.returncode


def run_version() -> int:
    mode = "dev checkout" if _is_dev_checkout() else "instalado"
    commit = get_installed_commit()
    print(f"call-copilot ({mode})")
    print(f"commit: {commit[:12] if commit else 'desconocido'}")
    return 0


def run_check_update() -> int:
    installed = get_installed_commit()
    ref = get_latest_release_tag()
    remote = get_remote_commit(ref)
    if remote is None:
        print("No se pudo consultar el repositorio remoto (¿sin conexión?).")
        return 1
    if installed is None:
        print("No se pudo determinar la versión instalada.")
        return 1
    if installed == remote:
        print(f"Estás al día ({ref}, commit {installed[:12]}).")
    else:
        print(f"Hay una versión nueva disponible: {ref} ({remote[:12]}) — tenés {installed[:12]}.")
        print("Corré 'call-copilot update' para actualizar.")
    return 0


def run_uninstall() -> int:
    try:
        result = subprocess.run(["pipx", "uninstall", "call-copilot"])
    except FileNotFoundError:
        print("pipx no está instalado.")
        return 1

    # pipx can report success even when Windows (AV/real-time scanning)
    # blocked it from fully removing the venv -- same root cause as
    # run_update()'s retry. Left behind, that venv silently breaks the
    # next install/update ("already seems to be installed"), so sweep it
    # ourselves regardless of what pipx reported.
    venvs_dir = _pipx_venvs_dir()
    if venvs_dir is not None:
        leftover = venvs_dir / "call-copilot"
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)

    if result.returncode == 0:
        print(f"\nTu configuración y datos siguen en {app_home()} — borralos a mano si querés limpiar todo.")
    return result.returncode


def _pipx_version() -> str | None:
    try:
        result = subprocess.run(
            ["pipx", "--version"], capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip()


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run_doctor() -> int:
    import sys

    print("═══ call-copilot doctor ═══")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Modo: {'dev checkout' if _is_dev_checkout() else 'instalado (pipx)'}")

    commit = get_installed_commit()
    print(f"Commit: {commit[:12] if commit else 'desconocido'}")

    pipx_version = _pipx_version()
    print(f"pipx: {pipx_version or 'no encontrado'}")

    print(f"Directorio de datos: {app_home()}")

    print("\nExtras opcionales:")
    for label, module_name in (
        ("rag (chromadb)", "chromadb"),
        ("whisper-local (faster-whisper)", "faster_whisper"),
        ("video (yt-dlp)", "yt_dlp"),
        ("video (openai-whisper)", "whisper"),
        ("video (imageio-ffmpeg)", "imageio_ffmpeg"),
    ):
        status = "instalado" if _module_available(module_name) else "no instalado"
        print(f"  {label}: {status}")

    if _module_available("torch"):
        import torch
        cuda = "disponible" if torch.cuda.is_available() else "no disponible — CPU"
        print(f"\ntorch: {torch.__version__} (CUDA {cuda})")
    else:
        print("\ntorch: no instalado (requerido — algo anda mal)")

    return 0
