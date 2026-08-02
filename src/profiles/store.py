"""
ProfileStore: loads and persists call profiles from data/profiles.json.

Responsibilities:
- Load profiles from JSON on construction; re-seed on corrupt/missing file.
- Provide list(), get(), add(), update(), delete(), get_active(), set_active().
- Persist every mutation immediately to JSON.
- On delete of active profile, revert active to the default ("reunion").
"""

import json
import logging
from pathlib import Path
from dataclasses import asdict

from src.profiles.models import CallProfile, ProfileHeuristics, ResponseMode

logger = logging.getLogger("call_copilot.profiles.store")

_DEFAULT_ACTIVE_ID = "reunion"

_DEFAULT_PROFILES: list[dict] = [
    {
        "id": "presentacion",
        "name": "Presentación",
        "description": "Para presentaciones y exposiciones. El orador explica, la audiencia escucha. Solo responde ante preguntas directas.",
        "system_prompt_addon": "Estás asistiendo en una presentación. El orador expone contenido. Solo sugiere respuesta si hay una pregunta directa y clara de la audiencia. Si el bloque es solo confirmaciones o marcadores de discurso, no respondas.",
        "heuristics": {
            "discourse_markers": ["¿Listo?", "¿Sí?", "¿Verdad?", "¿Entienden?", "¿Ok?", "¿De acuerdo?", "¿Claro?", "¿No?"],
            "require_real_question": True,
        },
        "response_mode": "silent",
        "model": "gpt-5.6-terra",
    },
    {
        "id": "entrevista",
        "name": "Entrevista",
        "description": "Para entrevistas de trabajo o técnicas. El entrevistador hace preguntas, el candidato responde.",
        "system_prompt_addon": "Estás asistiendo en una entrevista. Sugiere respuestas concisas y directas a las preguntas del entrevistador. Enfocate en demostrar competencia técnica o professional según el contexto.",
        "heuristics": {
            "discourse_markers": ["¿Sí?", "¿Ok?", "¿Listo?"],
            "require_real_question": False,
        },
        "response_mode": "copilot",
        "model": "gpt-5.4-mini",
    },
    {
        "id": "reunion",
        "name": "Reunión",
        "description": "Para reuniones de trabajo generales. Perfil balanceado, responde ante preguntas directas.",
        "system_prompt_addon": "",
        "heuristics": {
            "discourse_markers": ["¿Sí?", "¿Ok?", "¿Listo?", "¿De acuerdo?", "¿Verdad?"],
            "require_real_question": True,
        },
        "response_mode": "copilot",
        "model": "",
    },
    {
        "id": "ventas",
        "name": "Llamada de ventas",
        "description": "Para llamadas comerciales. Sugiere argumentos de venta y respuestas a objeciones.",
        "system_prompt_addon": "Estás asistiendo en una llamada de ventas. Sugiere argumentos que destaquen el valor del producto o servicio, y respuestas a objeciones comunes. Tono positivo y orientado a soluciones.",
        "heuristics": {
            "discourse_markers": ["¿Sí?", "¿Ok?", "¿Verdad?"],
            "require_real_question": False,
        },
        "response_mode": "copilot",
        "model": "gpt-5.4-mini",
    },
    {
        "id": "soporte",
        "name": "Soporte técnico",
        "description": "Para sesiones de soporte técnico. Sugiere pasos de diagnóstico y soluciones técnicas.",
        "system_prompt_addon": "Estás asistiendo en una sesión de soporte técnico. Sugiere pasos de diagnóstico claros, soluciones concretas y preguntas de clarificación para identificar el problema. Prioriza la solución más simple primero.",
        "heuristics": {
            "discourse_markers": ["¿Sí?", "¿Ok?", "¿Listo?"],
            "require_real_question": False,
        },
        "response_mode": "explain",
        "model": "gpt-5.4-mini",
    },
]


def _profile_from_dict(d: dict) -> CallProfile:
    heuristics_raw = d.get("heuristics", {})
    heuristics = ProfileHeuristics(
        discourse_markers=heuristics_raw.get("discourse_markers", []),
        require_real_question=heuristics_raw.get("require_real_question", False),
    )
    raw_mode = d.get("response_mode", "copilot")
    try:
        response_mode = ResponseMode(raw_mode)
    except ValueError:
        response_mode = ResponseMode.copilot
    return CallProfile(
        id=d["id"],
        name=d["name"],
        description=d.get("description", ""),
        system_prompt_addon=d.get("system_prompt_addon", ""),
        heuristics=heuristics,
        response_mode=response_mode,
        model=d.get("model", ""),
    )


def _profile_to_dict(p: CallProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "system_prompt_addon": p.system_prompt_addon,
        "heuristics": {
            "discourse_markers": p.heuristics.discourse_markers,
            "require_real_question": p.heuristics.require_real_question,
        },
        "response_mode": p.response_mode.value,
        "model": p.model,
    }


class ProfileStore:
    """
    Loads call profiles from a JSON file and persists changes.
    Re-seeds defaults on missing or corrupt file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path("data/profiles.json")
        self._profiles: dict[str, CallProfile] = {}
        self._active_id: str = _DEFAULT_ACTIVE_ID
        self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def list(self) -> list[CallProfile]:
        return list(self._profiles.values())

    def get(self, profile_id: str) -> CallProfile | None:
        return self._profiles.get(profile_id)

    def get_active(self) -> CallProfile:
        profile = self._profiles.get(self._active_id)
        if profile is None:
            # Fallback: active_id may have been deleted; reset to default
            self._active_id = _DEFAULT_ACTIVE_ID
            profile = self._profiles.get(_DEFAULT_ACTIVE_ID)
        return profile

    def set_active(self, profile_id: str) -> None:
        if profile_id not in self._profiles:
            raise KeyError(f"Profile '{profile_id}' not found")
        self._active_id = profile_id
        self._save()

    def add(self, profile: CallProfile) -> None:
        self._profiles[profile.id] = profile
        self._save()

    def update(self, profile: CallProfile) -> None:
        if profile.id not in self._profiles:
            raise KeyError(f"Profile '{profile.id}' not found")
        self._profiles[profile.id] = profile
        self._save()

    def delete(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)
        if self._active_id == profile_id:
            self._active_id = _DEFAULT_ACTIVE_ID
        self._save()

    # ── Internal ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            logger.info("profiles.json not found — seeding defaults")
            self.seed_defaults()
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            profiles_list = data["profiles"]
            self._profiles = {d["id"]: _profile_from_dict(d) for d in profiles_list}
            self._active_id = data.get("active_profile_id", _DEFAULT_ACTIVE_ID)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("profiles.json corrupt (%s) — re-seeding defaults", exc)
            self.seed_defaults()

    def seed_defaults(self) -> None:
        """Overwrite the file with the built-in default profiles."""
        self._profiles = {
            d["id"]: _profile_from_dict(d) for d in _DEFAULT_PROFILES
        }
        self._active_id = _DEFAULT_ACTIVE_ID
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "active_profile_id": self._active_id,
            "profiles": [_profile_to_dict(p) for p in self._profiles.values()],
        }
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
