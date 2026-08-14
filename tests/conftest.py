"""
Test configuration: stub out heavy third-party dependencies that are not
installed in the CI/test environment (openai, anthropic, chromadb, textual,
torch, faster_whisper, etc.) so that unit tests can import modules without
installing the full production stack.
"""

import sys
from unittest.mock import MagicMock


def _mock_module(name: str, **attrs) -> MagicMock:
    m = MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


# ── openai ────────────────────────────────────────────────────────────────────
if "openai" not in sys.modules:
    _mock_module("openai")
    _mock_module("openai.AsyncOpenAI")

# ── anthropic ─────────────────────────────────────────────────────────────────
if "anthropic" not in sys.modules:
    _mock_module("anthropic")

# ── chromadb ──────────────────────────────────────────────────────────────────
if "chromadb" not in sys.modules:
    _mock_module("chromadb")

# ── torch / torchaudio ────────────────────────────────────────────────────────
for _name in ["torch", "torchaudio", "torchaudio.transforms"]:
    if _name not in sys.modules:
        _mock_module(_name)

# ── faster_whisper ────────────────────────────────────────────────────────────
if "faster_whisper" not in sys.modules:
    _mock_module("faster_whisper")

# ── whisper (openai-whisper, used by src/video/pipeline.py) ───────────────────
if "whisper" not in sys.modules:
    _mock_module("whisper")

# ── textual ───────────────────────────────────────────────────────────────────
for _name in [
    "textual",
    "textual.app",
    "textual.widgets",
    "textual.containers",
    "textual.screen",
    "textual.reactive",
    "textual.binding",
    "textual.message",
    "textual.css",
    "textual.css.query",
]:
    if _name not in sys.modules:
        _mock_module(_name)

# ── numpy ─────────────────────────────────────────────────────────────────────
if "numpy" not in sys.modules:
    _mock_module("numpy")

# ── websockets ────────────────────────────────────────────────────────────────
if "websockets" not in sys.modules:
    _mock_module("websockets")

# ── dotenv ────────────────────────────────────────────────────────────────────
if "dotenv" not in sys.modules:
    _mock_module("dotenv")
    _mock_module("python_dotenv")
