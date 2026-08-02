#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt pyaudio
else
    source .venv/bin/activate
fi

PYTHONPATH="$SCRIPT_DIR" HF_HUB_DISABLE_PROGRESS_BARS=1 python src/tui/app.py
