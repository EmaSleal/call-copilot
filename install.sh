#!/bin/sh
# Call Copilot installer. POSIX sh — no bashisms — so it runs with plain
# `sh` on systems that don't have bash installed at all.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/EmaSleal/call-copilot/linux-support/install.sh | sh
#
# Installs call-copilot as a global command via pipx (no manual git clone
# needed — pipx clones the repo internally). Prompts once for which
# optional components to install; the choice is saved to
# ~/.call-copilot/install-profile so `call-copilot update` can reinstall
# later without asking again. Re-running this script (e.g. to switch
# profiles) is safe.
set -eu

REPO_URL="https://github.com/EmaSleal/call-copilot.git"
BRANCH="linux-support"
APP_HOME="$HOME/.call-copilot"

echo "═══════════════════════════════════════"
echo "  Call Copilot — instalador"
echo "═══════════════════════════════════════"
echo

# ── python3 ──────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 no está instalado. Instalalo y volvé a correr este script." >&2
    exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "Error: se requiere Python >= 3.10 (encontrado $PY_VERSION)." >&2
    exit 1
fi

# ── pipx ─────────────────────────────────────────────────────────────────
if ! command -v pipx >/dev/null 2>&1; then
    echo "pipx no está instalado — instalando con pip..."
    python3 -m pip install --user pipx
    python3 -m pipx ensurepath
    echo
    echo "pipx se instaló. Puede que necesites abrir una terminal nueva"
    echo "(o correr 'source ~/.bashrc' / equivalente de tu shell) para que"
    echo "'pipx' quede en el PATH. Volvé a correr este script después de eso."
    exit 0
fi

# ── perfil de instalación ────────────────────────────────────────────────
echo "¿Qué querés instalar?"
echo "  1) Mínimo   — solo llamadas en vivo (Deepgram + GPT/Claude/Ollama)"
echo "  2) Completo — todo (Whisper local, video, catálogo de tools con RAG)"
echo "  3) Elegir a mano"
printf "Elegí [1-3] (default: 1): "
read -r PROFILE_CHOICE
PROFILE_CHOICE="${PROFILE_CHOICE:-1}"

EXTRAS=""
case "$PROFILE_CHOICE" in
    1)
        EXTRAS=""
        ;;
    2)
        EXTRAS="whisper-local,video,rag"
        ;;
    3)
        printf "¿Whisper local para STT? [y/N]: "
        read -r ans
        case "$ans" in
            [Yy]*) EXTRAS="whisper-local" ;;
        esac

        printf "¿Procesar videos de YouTube? [y/N]: "
        read -r ans
        case "$ans" in
            [Yy]*)
                if [ -n "$EXTRAS" ]; then EXTRAS="$EXTRAS,video"; else EXTRAS="video"; fi
                ;;
        esac

        printf "¿Catálogo de tools con búsqueda semántica (RAG)? [y/N]: "
        read -r ans
        case "$ans" in
            [Yy]*)
                if [ -n "$EXTRAS" ]; then EXTRAS="$EXTRAS,rag"; else EXTRAS="rag"; fi
                ;;
        esac
        ;;
    *)
        echo "Opción inválida — instalo el perfil mínimo." >&2
        EXTRAS=""
        ;;
esac

# ── instalación ──────────────────────────────────────────────────────────
if [ -n "$EXTRAS" ]; then
    SPEC="call-copilot[$EXTRAS] @ git+${REPO_URL}@${BRANCH}"
else
    SPEC="call-copilot @ git+${REPO_URL}@${BRANCH}"
fi

echo
echo "Instalando: $SPEC"
# uninstall-then-install rather than `pipx install --force` — pipx's
# uv-backed venv creation refuses to clear a venv from a prior session on
# some setups, so --force fails outright there. Uninstalling a package
# that isn't installed yet (first run) exits nonzero — expected, ignored.
pipx uninstall call-copilot >/dev/null 2>&1 || true
pipx install "$SPEC"

mkdir -p "$APP_HOME"
echo "$EXTRAS" > "$APP_HOME/install-profile"

echo
echo "✓ Listo. Corré 'call-copilot' para arrancar."
echo "  Ctrl+S dentro de la app abre Configuración (API keys, backends)."
echo "  'call-copilot update' trae la última versión más adelante."
