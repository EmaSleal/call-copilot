"""
Data models for call profiles.

A CallProfile encapsulates:
- A system_prompt_addon injected into the LLM system prompt.
- Heuristics for the discourse-marker-only gate that sets conservative_mode.
- response_mode: controls which LLM system prompt template is used.
- model: optional model override (empty string = use pipeline default logic).
"""

from dataclasses import dataclass, field
from enum import Enum


class ResponseMode(str, Enum):
    """Controls which LLM behavior template is active for a profile."""
    copilot = "copilot"   # suggest brief answer / clarifying question (default)
    explain = "explain"   # expand/elaborate with context and background
    silent  = "silent"    # only respond if explicit audience question detected


# (model_id, display_label) pairs for the UI selector.
# model_id="" means "use pipeline default logic".
#
# FALLBACK ONLY as of config-settings-panel PR2: the #pm-model dropdown now
# sources live-discovered models via src.llm.model_catalog.list_models()
# first. This list is used only when no API key is configured for the
# active backend, or when the live discovery call fails (network/auth/
# rate-limit) — see model_catalog.list_models()'s fallback path. Keep this
# list's shape/ids unchanged: tests/unit/test_profile_models.py::TestAvailableModels
# asserts against it directly.
AVAILABLE_MODELS: list[tuple[str, str]] = [
    ("gpt-5.6-sol",   "GPT-5.6 Sol — máxima capacidad"),
    ("gpt-5.6-terra", "GPT-5.6 Terra — balance inteligencia/costo"),
    ("gpt-5.6-luna",  "GPT-5.6 Luna — optimizado para volumen"),
    ("gpt-5.4-mini",  "GPT-5.4 Mini — contexto grande"),
    ("gpt-5.4-nano",  "GPT-5.4 Nano — rápido y económico"),
    ("",              "Default — selección automática por contexto"),
]


@dataclass
class ProfileHeuristics:
    """Heuristics for determining when to apply conservative mode."""
    discourse_markers: list[str] = field(default_factory=list)
    require_real_question: bool = False


@dataclass
class CallProfile:
    """A named preset that steers LLM behavior for a particular call context."""
    id: str
    name: str
    description: str
    system_prompt_addon: str = ""
    heuristics: ProfileHeuristics = field(default_factory=ProfileHeuristics)
    response_mode: ResponseMode = ResponseMode.copilot
    model: str = ""   # empty = use pipeline default logic; never None
