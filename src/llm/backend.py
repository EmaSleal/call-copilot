"""
Shared sync one-shot LLM backend selector (claude/ollama/gpt) for batch
processing: segment classification, category suggestion/dedup/parent-naming
(src/video/classifier.py), call transcript grouping
(src/processing/session_processor.py), and tool extraction
(src/processing/tool_extractor.py) — previously each hand-rolled an
identical claude/ollama/gpt triple-branch, verbatim duplicated in the
latter two.

Distinct from src/llm/*_provider.py's async STREAMING LLMProvider
implementations used by the live call-copilot pipeline: those yield partial
response deltas and don't support ollama, whereas every caller here needs
one blocking call per batch.

Backend selection: LLM_BACKEND env var (ollama | gpt | claude), default ollama.
"""

import os

import anthropic
import openai


def call_llm_backend(
    prompt: str,
    system: str,
    backend: str,
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    ollama_num_ctx: int = 4096,
) -> str:
    """One blocking call to the given backend, returning the raw response text."""
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
