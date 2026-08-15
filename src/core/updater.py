"""
call-copilot package-lifecycle commands: update, check-update, version,
uninstall, doctor. Dispatched from src/core/cli.py.
"""

import importlib.metadata
import importlib.util
import subprocess

from src.core.paths import _is_dev_checkout, _REPO_ROOT, app_home

_REPO_URL = "https://github.com/EmaSleal/call-copilot.git"
_BRANCH = "linux-support"
_GIT_SPEC = f"git+{_REPO_URL}@{_BRANCH}"


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


def get_remote_commit(branch: str = _BRANCH) -> str | None:
    """Latest commit SHA on the given branch of the public repo, via
    `git ls-remote` — no API token/auth complexity, git is guaranteed
    present (pipx needs it to install from a git URL in the first place)."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", _REPO_URL, branch],
            capture_output=True, text=True, check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    line = result.stdout.strip()
    if not line:
        return None
    return line.split()[0]


def run_update() -> int:
    """Uninstall-then-install rather than `pipx install --force` — pipx's
    uv-backed venv creation refuses to clear a venv from a prior session,
    so --force fails outright on some setups. `pipx uninstall` on a
    not-yet-installed package returns nonzero; that's expected on a first
    run and must not block the install that follows."""
    extras = read_install_profile()
    spec = build_pip_spec(extras)
    print(f"Actualizando call-copilot ({extras or 'sin extras'})...")
    try:
        subprocess.run(["pipx", "uninstall", "call-copilot"])
        result = subprocess.run(["pipx", "install", spec])
    except FileNotFoundError:
        print("pipx no está instalado — no se puede actualizar. Volvé a correr install.sh.")
        return 1
    return result.returncode


def run_version() -> int:
    mode = "dev checkout" if _is_dev_checkout() else "instalado"
    commit = get_installed_commit()
    print(f"call-copilot ({mode})")
    print(f"commit: {commit[:12] if commit else 'desconocido'}")
    return 0


def run_check_update() -> int:
    installed = get_installed_commit()
    remote = get_remote_commit()
    if remote is None:
        print("No se pudo consultar el repositorio remoto (¿sin conexión?).")
        return 1
    if installed is None:
        print("No se pudo determinar la versión instalada.")
        return 1
    if installed == remote:
        print(f"Estás al día (commit {installed[:12]}).")
    else:
        print(f"Hay una versión nueva disponible: {remote[:12]} (tenés {installed[:12]}).")
        print("Corré 'call-copilot update' para actualizar.")
    return 0


def run_uninstall() -> int:
    try:
        result = subprocess.run(["pipx", "uninstall", "call-copilot"])
    except FileNotFoundError:
        print("pipx no está instalado.")
        return 1
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
