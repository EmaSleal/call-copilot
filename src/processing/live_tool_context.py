"""Cheap, network-free tool-mention detection for the live call pipeline
(docs/next-steps/feature-proposals.md point 3). Matches known catalog tool
names against the current speech block via plain regex — no LLM, no
embeddings — so it's safe on `CallCopilotPipeline._handle_trigger`'s hot
path. On a match, surfaces that tool's most recent past-session mention
(`src/db/tool_mentions.py`, populated post-session by
`src/processing/tool_extractor.py::ingest_tools`) as extra context for the
LLM prompt.
"""

import re

from src.db.database import Tool
from src.db.tool_mentions import get_tool_mentions

_MIN_NAME_LENGTH = 3  # shorter normalized names (e.g. "go", "r") are too generic to match safely


def detect_mentioned_tools(text: str, tools: list[Tool]) -> list[Tool]:
    """Catalog tools whose normalized name appears as a whole word in
    `text`, case-insensitive. Skips names shorter than `_MIN_NAME_LENGTH`
    to avoid matching short/generic names inside unrelated words."""
    lowered = text.lower()
    matched = []
    for tool in tools:
        name = tool.normalized_name
        if not name or len(name) < _MIN_NAME_LENGTH:
            continue
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            matched.append(tool)
    return matched


def build_live_tool_context(tools: list[Tool]) -> str:
    """One line per tool with its most recent past-session mention
    (`context_snippet`), oldest mentions ignored. Empty string when none of
    the given tools has any recorded past mention."""
    lines = []
    for tool in tools:
        mentions = get_tool_mentions(tool.id)
        if not mentions:
            continue
        last = mentions[-1]
        lines.append(
            f"{tool.name} (mencionado antes, {last.created_at[:10]}): {last.context_snippet}"
        )
    return "\n".join(lines)
