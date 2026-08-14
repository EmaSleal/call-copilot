"""
Post-session processor for Call Copilot.

Reads a transcript file produced by SessionLogger, groups its content
into coherent ideas via a one-shot LLM call, classifies each idea using
the existing classify_segments_batch, and persists them as CallSegment
rows linked to the call session.

Supported LLM backends: ollama (default) | gpt | claude
  — mirrors the same backend-switch pattern as src/video/classifier.py.

Open question (X.2): per-backend token ceiling for the grouper.
  - claude (claude-haiku-4-5-20251001): 4 096 output tokens max, 200 000 context
  - gpt (gpt-5.4-nano): no published hard cap; using 2 048 to stay conservative
  - ollama (qwen3:4b): model-dependent; 4 096 context by default; using num_ctx=8192
  Transcripts are typically < 5 000 chars so these limits are rarely hit.
"""

import json
import logging
import os
import re
from typing import Optional

import anthropic
import openai

from src.db.database import CallSegment, get_categories, save_call_segment
from src.processing.search_indexer import index_segment
from src.processing.tool_extractor import ingest_tools
from src.video.classifier import classify_segments_batch

logger = logging.getLogger("call_copilot.processing.session_processor")

# Minimum character count for the stripped transcript to warrant LLM processing.
_MIN_CHARS = 200

_GROUPER_SYSTEM = (
    "You are a conversation analyst. Divide the transcript into coherent topic ideas.\n"
    "Respond ONLY with valid JSON in this exact format (no text before or after):\n"
    '{"ideas": [{"title": "...", "text": "..."}]}\n'
    "Each idea should be a self-contained topic chunk from the conversation."
)

# Regex patterns for stripping non-spoken content from the transcript file.
_HEADER_RE = re.compile(r"^=== Sesión .+ ===\s*$")
_CONTEXT_HEADER_RE = re.compile(r"^Contexto inicial:.*$")
_TIMESTAMP_BLOCK_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] (CONTEXTO|RESPUESTA):?\s*$")
_SEPARATOR_RE = re.compile(r"^─+\s*$")
_TIMESTAMP_PREFIX_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\] ")


def _strip_transcript(raw: str) -> str:
    """
    Extract only spoken transcript lines from a SessionLogger output file.

    Removes:
      - Header line: '=== Sesión ... ==='
      - Initial context: 'Contexto inicial: ...'
      - CONTEXTO / RESPUESTA block headers and their following content lines
      - Horizontal separator lines (────)
      - Blank lines

    Keeps:
      - Lines starting with '[HH:MM:SS]' that are NOT CONTEXTO/RESPUESTA headers,
        stripped of their timestamp prefix.
    """
    lines = raw.splitlines()
    spoken: list[str] = []
    skip_until_separator = False

    for line in lines:
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            skip_until_separator = False
            continue

        # Skip separator lines
        if _SEPARATOR_RE.match(stripped):
            skip_until_separator = False
            continue

        # Skip session header
        if _HEADER_RE.match(stripped):
            continue

        # Skip initial context header
        if _CONTEXT_HEADER_RE.match(stripped):
            continue

        # CONTEXTO / RESPUESTA block header — skip this line and the next content block
        if _TIMESTAMP_BLOCK_RE.match(stripped):
            skip_until_separator = True
            continue

        if skip_until_separator:
            continue

        # Spoken transcript line: '[HH:MM:SS] actual speech'
        m = _TIMESTAMP_PREFIX_RE.match(stripped)
        if m:
            text = stripped[m.end():]
            if text:
                spoken.append(text)
            continue

        # Any other non-empty line (edge case) — keep as spoken text
        spoken.append(stripped)

    return "\n".join(spoken)


def _chunk_fallback(text: str) -> list[dict]:
    """
    Fallback splitter when the grouper LLM returns invalid JSON.

    Splits the transcript into blocks of up to 5 sentences each.
    Each block becomes one idea with an empty title.
    """
    # Split on sentence-ending punctuation followed by whitespace or end-of-string.
    sentence_re = re.compile(r"(?<=[.!?])\s+")
    sentences = [s.strip() for s in sentence_re.split(text) if s.strip()]

    if not sentences:
        return [{"title": "", "text": text.strip()}] if text.strip() else []

    chunk_size = 5
    ideas = []
    for i in range(0, len(sentences), chunk_size):
        block = " ".join(sentences[i : i + chunk_size])
        ideas.append({"title": "", "text": block})
    return ideas


def _call_grouper_llm(transcript: str) -> str:
    """
    Send transcript to the configured LLM backend and return the raw response string.

    Uses the same LLM_BACKEND env var as the classifier (ollama | gpt | claude).
    This is a private function so tests can patch it at the module level.
    """
    backend = os.getenv("LLM_BACKEND", "ollama")

    if backend == "claude":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            # Grouper needs more tokens than the 512 classifier cap —
            # long transcripts may produce many idea chunks.
            max_tokens=2048,
            system=_GROUPER_SYSTEM,
            messages=[{"role": "user", "content": transcript}],
        )
        return msg.content[0].text

    if backend == "ollama":
        client = openai.OpenAI(
            api_key="ollama",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        )
        resp = client.chat.completions.create(
            model=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
            max_completion_tokens=2048,
            temperature=0.3,
            messages=[
                {"role": "system", "content": _GROUPER_SYSTEM},
                {"role": "user", "content": "/no_think\n" + transcript},
            ],
            extra_body={"options": {"think": False, "num_ctx": 8192}},
        )
        return resp.choices[0].message.content

    # default: gpt
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-5.4-nano",
        max_completion_tokens=2048,
        temperature=0.3,
        messages=[
            {"role": "system", "content": _GROUPER_SYSTEM},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _parse_grouper_response(raw: str) -> Optional[list[dict]]:
    """
    Parse the grouper LLM response into a list of idea dicts.

    Returns a list of {"title": str, "text": str} or None on parse failure.
    """
    try:
        data = json.loads(raw)
        ideas = data.get("ideas", [])
        if isinstance(ideas, list):
            return ideas
        return None
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None


def process(call_session_id: int, transcript_path: str) -> int:
    """
    Group, classify, and persist ideas from a call session transcript.

    Steps:
      1. Read transcript file; skip if missing/unreadable.
      2. Strip timestamps, headers, CONTEXTO/RESPUESTA blocks.
      3. Skip if stripped text is below _MIN_CHARS threshold.
      4. Call grouper LLM → parse JSON ideas.
      5. On parse failure, fall back to sentence-chunk splitting.
      6. Skip if ideas list is empty.
      7. Classify ideas via classify_segments_batch.
      8. Persist each idea as a CallSegment row.
      9. Ingest concrete tools mentioned in the transcript (best-effort, isolated).

    Returns:
      Number of ideas persisted (0 if skipped or empty).
    """
    # Step 1: read file
    try:
        with open(transcript_path, encoding="utf-8") as f:
            raw = f.read()
    except (OSError, IOError) as exc:
        logger.info("session %d: transcript not readable (%s) — skipping", call_session_id, exc)
        return 0

    # Step 2: strip non-spoken content
    spoken_text = _strip_transcript(raw)

    # Step 3: threshold guard
    if len(spoken_text) < _MIN_CHARS:
        logger.info(
            "session %d: stripped transcript too short (%d chars < %d) — skipping",
            call_session_id, len(spoken_text), _MIN_CHARS,
        )
        return 0

    # Step 4: call grouper LLM
    raw_response = _call_grouper_llm(spoken_text)

    # Step 5: parse; fall back to chunking on failure
    ideas = _parse_grouper_response(raw_response)
    if ideas is None:
        logger.warning(
            "session %d: grouper returned invalid JSON — using chunk fallback. raw=%r",
            call_session_id, raw_response[:200],
        )
        ideas = _chunk_fallback(spoken_text)

    # Step 6: skip if empty
    if not ideas:
        logger.info("session %d: no ideas to persist — done", call_session_id)
        return 0

    # Step 7: classify
    categories = get_categories()
    idea_texts = [idea.get("text", "") for idea in ideas]
    category_ids: list[Optional[int]] = classify_segments_batch(idea_texts, categories)

    # Step 8: persist
    saved = 0
    persisted_segments: list[tuple[int, str]] = []
    for i, (idea, cat_id) in enumerate(zip(ideas, category_ids)):
        text = idea.get("text", "")
        seg = CallSegment(
            id=None,
            call_session_id=call_session_id,
            sort_order=i,
            text=text,
            category_id=cat_id,
        )
        new_id = save_call_segment(seg)
        persisted_segments.append((new_id, text))
        saved += 1

    logger.info("session %d: %d idea(s) persisted", call_session_id, saved)

    # Step 9: Tools Catalog ingestion — best-effort, must never affect idea
    # persistence. Any failure (extraction, dedup, persistence, or embedding)
    # is caught and logged here.
    try:
        ingest_tools(call_session_id, spoken_text)
    except Exception as exc:
        logger.error("session %d: tools ingestion failed (%s)", call_session_id, exc)

    # Step 10: semantic search indexing — best-effort, coexists with the
    # full-text SQL search and must never affect idea persistence either.
    try:
        for seg_id, text in persisted_segments:
            index_segment("call", seg_id, text)
    except Exception as exc:
        logger.error("session %d: search indexing failed (%s)", call_session_id, exc)

    return saved
