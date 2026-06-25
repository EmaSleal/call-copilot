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


def _call_llm(prompt: str, backend: str) -> str:
    if backend == "claude":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM,
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
            max_completion_tokens=512,
            temperature=0.0,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": "/no_think\n" + prompt},
            ],
            extra_body={"options": {"think": False}},
        )
        return resp.choices[0].message.content

    # default: gpt
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-5.4-nano",
        max_completion_tokens=512,
        temperature=0.0,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content
