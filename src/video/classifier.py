"""
Batch segment classifier. Classifies BATCH_SIZE segments per LLM call
instead of one at a time, reducing API calls from N to ceil(N/BATCH_SIZE).

Supported backends (LLM_BACKEND env var): ollama (default) | gpt | claude
"""

import json
import logging
import os
from typing import Optional

import anthropic
import openai

from src.db.database import Category

logger = logging.getLogger("unified.classifier")

BATCH_SIZE = 30

_SYSTEM = """You are a content classifier. Given a numbered list of transcript fragments and available categories, classify each one.

Respond ONLY with valid JSON in this exact format:
{"classifications": [{"idx": 0, "category_id": 2}, {"idx": 1, "category_id": null}]}

One entry per fragment. Use null for category_id if no category fits. No text before or after the JSON."""


def _build_prompt(texts: list[str], categories: list[Category]) -> str:
    cats_str = "\n".join(
        f"  - ID {c.id}: {c.name} — {c.description}"
        for c in categories
    )
    fragments = "\n".join(f'[{i}] "{t[:400]}"' for i, t in enumerate(texts))
    return (
        f"Available categories:\n{cats_str}\n\n"
        f"Fragments to classify:\n{fragments}\n\n"
        "Return the JSON classifications array."
    )


def _parse_response(raw: str) -> list[dict]:
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if "classifications" in data:
        return data["classifications"]
    for v in data.values():
        if isinstance(v, list):
            return v
    raise ValueError(f"unexpected JSON shape: {list(data.keys())}")


def classify_segments_batch(
    texts: list[str],
    categories: list[Category],
) -> list[Optional[int]]:
    """
    Classifies texts in batches of BATCH_SIZE.
    Returns a list of category_ids (or None) aligned with input texts.
    """
    if not categories or not texts:
        return [None] * len(texts)

    results: list[Optional[int]] = [None] * len(texts)
    backend = os.getenv("LLM_BACKEND", "ollama")
    valid_ids = {c.id for c in categories}

    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start : batch_start + BATCH_SIZE]
        prompt = _build_prompt(batch, categories)
        raw = ""
        try:
            raw = _call_llm(prompt, backend)
            entries = _parse_response(raw)
            for entry in entries:
                local_idx = int(entry["idx"])
                cat_id = entry.get("category_id")
                if cat_id is not None:
                    cat_id = int(cat_id)
                    if cat_id not in valid_ids:
                        logger.warning("unknown category_id=%d from LLM", cat_id)
                        cat_id = None
                global_idx = batch_start + local_idx
                if 0 <= global_idx < len(texts):
                    results[global_idx] = cat_id
            logger.debug(
                "batch %d-%d classified (%d entries)",
                batch_start, batch_start + len(batch) - 1, len(entries),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.error(
                "parse error at offset %d: %s | raw=%r", batch_start, e, raw[:300]
            )
        except Exception as e:
            logger.error("LLM error at offset %d: %s", batch_start, e)

    return results


_SUGGEST_SYSTEM = """You are a content analyst. Given transcript segments that don't fit existing categories, identify recurring themes and suggest new categories.

Respond ONLY with valid JSON:
{"suggestions": [{"name": "Category Name", "description": "One sentence description"}, ...]}

Rules:
- Suggest 2 to 5 categories maximum
- Only suggest a category if it appears in at least 2 segments
- Keep names short (1-3 words)
- Descriptions must be GENERAL: define the topic/theme itself, reusable to classify similar content in a completely different video — NOT a summary of these specific segments. Never mention specific names, products, people, or examples that only appear in this particular analysis.
  Bad (too specific): "Habla de ajustar el comportamiento del clon mediante reglas, versiones y memoria de Juan."
  Good (general): "Ajustes y personalización del comportamiento del asistente mediante reglas y contexto."
- No text before or after the JSON"""


def suggest_new_categories(
    texts: list[str],
    existing_categories: list[Category],
) -> list[dict]:
    """
    Analyzes up to 50 sampled texts from 'Otros' segments and suggests new categories.
    Returns list of {name, description} dicts, empty list on failure.
    """
    if not texts:
        return []

    # Sample evenly if too many segments
    if len(texts) > 50:
        step = len(texts) // 50
        texts = texts[::step][:50]

    backend = os.getenv("LLM_BACKEND", "ollama")
    existing_str = "\n".join(
        f"  - {c.name}: {c.description}" for c in existing_categories
    )
    fragments = "\n".join(f'[{i}] "{t[:300]}"' for i, t in enumerate(texts))
    prompt = (
        f"Existing categories (do NOT suggest these again):\n{existing_str}\n\n"
        f"Uncategorized segments:\n{fragments}\n\n"
        "Suggest new categories that cover recurring themes in these segments."
    )

    try:
        raw = _call_suggest_llm(prompt, backend)
        data = json.loads(raw)
        suggestions = data.get("suggestions", [])
        return [s for s in suggestions if s.get("name") and s.get("description")]
    except Exception as e:
        logger.error("suggest_new_categories failed: %s", e)
        return []


def _call_backend(
    prompt: str,
    system: str,
    backend: str,
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    ollama_num_ctx: int = 4096,
) -> str:
    """Shared triple-branch (claude/ollama/gpt) LLM call, extracted from the
    formerly-duplicated bodies of `_call_llm` and `_call_suggest_llm` (design
    decision A5). All three callers (`_call_llm`, `_call_suggest_llm`,
    `_call_judge_llm`) delegate here — request shape per backend is
    characterized by tests/unit/test_classifier_judge.py, written before this
    extraction existed."""
    if backend == "claude":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    if backend == "ollama":
        client = openai.OpenAI(
            api_key="ollama",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        )
        resp = client.chat.completions.create(
            model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
            max_completion_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "/no_think\n" + prompt},
            ],
            extra_body={"options": {"think": False, "num_ctx": ollama_num_ctx}},
        )
        return resp.choices[0].message.content

    # default: gpt
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(
        model="gpt-5.4-nano",
        max_completion_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        **kwargs,
    )
    return resp.choices[0].message.content


def _call_suggest_llm(prompt: str, backend: str) -> str:
    return _call_backend(
        prompt, _SUGGEST_SYSTEM, backend,
        temperature=0.3, max_tokens=512, json_mode=True, ollama_num_ctx=8192,
    )


def _call_llm(prompt: str, backend: str) -> str:
    return _call_backend(
        prompt, _SYSTEM, backend,
        temperature=0.0, max_tokens=512, json_mode=True, ollama_num_ctx=4096,
    )


_JUDGE_SYSTEM = (
    "You decide whether a proposed content category duplicates one that already "
    "exists. Respond ONLY with valid JSON: "
    '{"verdict":"MATCH","category_id":12} or {"verdict":"NEW","category_id":null}. '
    "Rules: MATCH only when an existing category already covers essentially the "
    "same topic; a broader or merely adjacent topic is NOT a match. When unsure, "
    "answer NEW. No text before or after the JSON."
)


def _build_judge_prompt(name: str, description: str, existing: list[Category]) -> str:
    existing_str = "\n".join(
        f"- ID {c.id}: {c.name} — {c.description}" for c in existing
    )
    return (
        f"Existing categories:\n{existing_str}\n\n"
        f"Proposed category: {name} — {description}\n\n"
        "Does the proposed category duplicate one of the existing ones?"
    )


def _call_judge_llm(prompt: str, backend: str) -> str:
    return _call_backend(
        prompt, _JUDGE_SYSTEM, backend,
        temperature=0.0, max_tokens=128, json_mode=True, ollama_num_ctx=4096,
    )


def judge_category_duplicate(
    name: str,
    description: str,
    existing: list[Category],
) -> Optional[int]:
    """Id of an existing category that already covers (name, description), else None.

    Fail-open (spec: Fail-open on any uncertainty): every error, timeout, or
    unparseable output returns None rather than raising or matching by default.
    """
    if not existing:
        return None

    backend = os.getenv("LLM_BACKEND", "ollama")
    valid_ids = {c.id for c in existing}
    prompt = _build_judge_prompt(name, description, existing)

    try:
        raw = _call_judge_llm(prompt, backend)
        data = json.loads(raw)
        verdict = data.get("verdict")
        category_id = data.get("category_id")
        if verdict == "MATCH" and category_id is not None and int(category_id) in valid_ids:
            return int(category_id)
        return None
    except Exception as e:
        logger.error("judge_category_duplicate failed: %s", e)
        return None
