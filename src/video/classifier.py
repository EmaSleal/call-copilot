"""
Clasifica un segmento de transcripción contra las categorías disponibles en BD.
El LLM recibe el texto + la lista de categorías y devuelve el ID más apropiado.
Usa JSON estructurado para que la respuesta sea parseable sin ambigüedad.
"""

import json
import logging
import os
from typing import Optional

import anthropic
import openai

from src.db.database import Category

logger = logging.getLogger("unified.classifier")

_SYSTEM = """Sos un clasificador de contenido. Se te dará un fragmento de transcripción
y una lista de categorías disponibles. Tu única tarea es elegir la categoría más apropiada.

Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:
{"category_id": <id numérico>, "confidence": <0.0 a 1.0>, "reason": "<1 oración breve>"}

No agregues texto antes ni después del JSON."""


def _build_prompt(text: str, categories: list[Category]) -> str:
    cats_str = "\n".join(
        f"  - ID {c.id}: {c.name} — {c.description}"
        for c in categories
    )
    return (
        f"Categorías disponibles:\n{cats_str}\n\n"
        f"Fragmento de transcripción:\n\"{text[:800]}\"\n\n"
        "¿A qué categoría corresponde este fragmento?"
    )


def classify_segment(text: str, categories: list[Category]) -> Optional[int]:
    """
    Devuelve el category_id asignado por el LLM, o None si falla.
    Usa el mismo backend configurado en el entorno (gpt | claude).
    """
    if not categories:
        return None

    prompt = _build_prompt(text, categories)
    backend = os.getenv("LLM_BACKEND", "gpt")

    try:
        raw = _call_llm(prompt, backend)
        data = json.loads(raw)
        cat_id = int(data["category_id"])
        # Validar que el ID existe en la lista recibida
        valid_ids = {c.id for c in categories}
        if cat_id not in valid_ids:
            logger.warning("LLM devolvió category_id=%d que no existe en BD", cat_id)
            return None
        logger.debug("clasificado: id=%d confidence=%.2f reason=%s",
                     cat_id, data.get("confidence", 0), data.get("reason", ""))
        return cat_id
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("error parseando respuesta del clasificador: %s | raw=%r", e, raw[:200])
        return None
    except Exception as e:
        logger.error("error en clasificador LLM: %s", e)
        return None


def _call_llm(prompt: str, backend: str) -> str:
    if backend == "claude":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    # default: gpt
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-5.4-nano",   # nano es suficiente para clasificación
        max_completion_tokens=150,
        temperature=0.0,        # determinismo máximo para clasificación
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content
