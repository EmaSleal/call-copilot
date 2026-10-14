"""
Defaults canónicos de proveedor/backend en tiempo real, compartidos por
main.py y src/tui/app.py.

Módulo de solo lectura: cero I/O más allá de os.getenv, cero dependencias
pesadas — seguro de importar desde el hot path (pipeline.py) sin arrastrar
dotenv ni escritura a disco. La contraparte de escritura vive en
src/core/env_store.py, deliberadamente separada por esa misma razón.

Nota: el clasificador batch (src/processing/classifier.py,
src/processing/session_processor.py) lee la MISMA variable LLM_BACKEND pero
con su propio default ("ollama") aplicado inline — eso queda fuera de
alcance de este módulo (ver Non-Goals del diseño de config-settings-panel).
"""

import os
from enum import Enum
from pathlib import Path

DEFAULT_LLM_BACKEND = "gpt"
DEFAULT_STT_BACKEND = "deepgram"
DEFAULT_WHISPER_MODEL_CALL = "large-v3-turbo"
DEFAULT_SILENCE_THRESHOLD_MS = 2000
DEFAULT_LANGUAGE = "en"

WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")


class Scope(str, Enum):
    """Cuándo un cambio de configuración toma efecto."""

    RESTART = "restart"
    NEXT_CALL = "next_call"
    MCP_RESTART = "mcp_restart"


# Claves que requieren reiniciar el proceso porque su valor queda "congelado"
# en un singleton cargado antes de que Textual abra la terminal
# (_preload_models en src/tui/bootstrap.py).
RESTART_KEYS = {"STT_BACKEND", "WHISPER_MODEL_CALL", "SILENCE_THRESHOLD_MS"}

# MCP_RESTART is distinct from RESTART: restarting the TUI process does
# nothing for this — src/mcp/server.py runs as a SEPARATE process
# launched by an external MCP client (e.g. Claude Desktop), which is the
# process that actually needs restarting to pick up the new value via
# load_dotenv() at its own startup.
_SCOPE_MAP: dict[str, Scope] = {
    "STT_BACKEND": Scope.RESTART,
    "WHISPER_MODEL_CALL": Scope.RESTART,
    "SILENCE_THRESHOLD_MS": Scope.RESTART,
    "MCP_ALLOW_TOOL_INGESTION": Scope.MCP_RESTART,
}


def _getenv_or_default(key: str, default: str) -> str:
    """os.getenv(key) tratando la cadena vacía como "no configurado"."""
    return os.getenv(key) or default


def llm_backend() -> str:
    """Backend LLM en tiempo real (Call Copilot). Default: 'gpt'."""
    return _getenv_or_default("LLM_BACKEND", DEFAULT_LLM_BACKEND)


def stt_backend() -> str:
    """Backend STT en tiempo real. Default: 'deepgram'."""
    return _getenv_or_default("STT_BACKEND", DEFAULT_STT_BACKEND)


def whisper_model_call() -> str:
    """
    Tamaño de modelo Whisper local para llamadas en vivo.

    Orden de resolución: WHISPER_MODEL_CALL → WHISPER_MODEL (legado) →
    default. La cadena vacía cuenta como "no configurado" en cada paso.
    """
    value = os.getenv("WHISPER_MODEL_CALL") or os.getenv("WHISPER_MODEL")
    return value or DEFAULT_WHISPER_MODEL_CALL


def tech_scout_db_path() -> str:
    """Path to tech-scout's tools.db, source for the Settings 'sync' action.
    Default assumes tech-scout's own default layout on this machine."""
    default = str(Path.home() / ".hermes" / "tech-scout" / "tools.db")
    return _getenv_or_default("TECH_SCOUT_DB_PATH", default)


def silence_threshold_ms() -> int:
    """
    Milisegundos de silencio sostenido antes de que el VAD dispare fin de
    turno. Un valor inválido o ausente cae al default sin romper el arranque.
    """
    value = os.getenv("SILENCE_THRESHOLD_MS")
    if not value:
        return DEFAULT_SILENCE_THRESHOLD_MS
    try:
        return int(value)
    except ValueError:
        return DEFAULT_SILENCE_THRESHOLD_MS


def language() -> str:
    """Idioma activo de la UI ('es' o 'en'). Default: 'en'."""
    return _getenv_or_default("LANGUAGE", DEFAULT_LANGUAGE)


def mcp_allow_tool_ingestion() -> bool:
    """Whether the MCP server's save_tool write tool is enabled. Off by
    default — same parsing as src/mcp/server.py's own gate."""
    return os.getenv("MCP_ALLOW_TOOL_INGESTION", "false").lower() == "true"


def scope_of(key: str) -> Scope:
    """
    Devuelve el Scope de una clave de configuración: cuándo un cambio a esa
    clave toma efecto. Claves no listadas explícitamente (LLM_BACKEND, las
    tres API keys, etc.) caen en NEXT_CALL — ninguna de ellas está congelada
    en un singleton pre-cargado.
    """
    return _SCOPE_MAP.get(key, Scope.NEXT_CALL)
