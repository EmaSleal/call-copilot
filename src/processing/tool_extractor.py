"""
Tools Catalog extraction for Call Copilot.

Identifies concrete named tools/products/libraries/platforms mentioned in a
call transcript, deduplicates them against the persistent tools catalog,
and records a per-call mention (consumed later by
src/processing/live_tool_context.py's live in-call trigger).

Supported LLM backends: ollama (default) | gpt | claude
  — mirrors the same backend-switch pattern as src/processing/session_processor.py.
"""

import json
import logging
import os
import sqlite3
from pathlib import Path

from src.db.database import (
    Tool,
    ToolMention,
    create_tool,
    find_tool_by_name,
    get_tools,
    normalize_tool_name,
    save_tool_mention,
)
from src.llm.backend import call_llm_backend

logger = logging.getLogger("call_copilot.processing.tool_extractor")

_TOOLS_SYSTEM = (
    "You are a technical analyst. Identify concrete tools mentioned in the transcript.\n"
    "A tool is a NAMED product, library, framework, platform, service, or database "
    '(e.g. "Chroma", "Deepgram", "React", "PostgreSQL").\n'
    "NEVER extract abstract concepts, patterns, or methodologies as tools "
    '(Bad: "vector database", "hexagonal architecture", "CI/CD", "RAG". '
    'Good: "Chroma", "Deepgram", "React").\n'
    "Use each tool's canonical name, not how it was spoken.\n"
    "Respond ONLY with valid JSON in this exact format (no text before or after):\n"
    '{"tools": [{"name": "...", "category": "...", "description": "...", '
    '"summary": "...", "tags": "...", "context_snippet": "..."}]}\n'
    "name: canonical product name. category: free text, 1-3 words. "
    "description: general, reusable info about the tool (not call-specific). "
    "summary: specific to what was discussed in THIS call. "
    "tags: comma-separated keywords. "
    "context_snippet: a verbatim quote from the transcript mentioning the tool.\n"
    'Return {"tools": []} when the transcript names no concrete tools.'
)


def _call_tools_llm(transcript: str) -> str:
    """
    Send transcript to the configured LLM backend and return the raw response string.

    Uses the same LLM_BACKEND env var as session_processor's grouper.
    This is a private function so tests can patch it at the module level.
    """
    backend = os.getenv("LLM_BACKEND", "ollama")
    return call_llm_backend(
        transcript, _TOOLS_SYSTEM, backend,
        temperature=0.3, max_tokens=2048, json_mode=True, ollama_num_ctx=8192,
    )


def _parse_tools_response(raw: str) -> list[dict]:
    """
    Parse the tools LLM response into a list of tool dicts.

    Returns [] on any parse failure — no chunk-fallback exists for tool
    extraction; zero tools is the confirmed silent-normal case.
    """
    try:
        data = json.loads(raw)
        tools = data.get("tools", [])
        if isinstance(tools, list):
            return tools
        return []
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []


def ingest_tools(call_session_id: int, spoken_text: str) -> int:
    """
    Extract concrete tools mentioned in spoken_text, dedup/persist them, and
    record a mention for this call.

    Runs regardless of LLM_BACKEND and regardless of OPENAI_API_KEY
    availability.

    Returns the number of tools touched (created or re-mentioned).
    """
    raw_response = _call_tools_llm(spoken_text)
    extracted = _parse_tools_response(raw_response)
    if not extracted:
        return 0

    touched_tools: list[Tool] = []
    for item in extracted:
        name = (item.get("name") or "").strip()
        if not name:
            continue

        existing = find_tool_by_name(name)
        if existing is None:
            tool = create_tool(
                Tool(
                    id=None,
                    name=name,
                    normalized_name=normalize_tool_name(name),
                    category=item.get("category", "") or "",
                    description=item.get("description", "") or "",
                    summary=item.get("summary", "") or "",
                    tags=item.get("tags", "") or "",
                )
            )
        else:
            # Dedup hit: never overwrite existing enrichment.
            tool = existing

        save_tool_mention(
            ToolMention(
                id=None,
                tool_id=tool.id,
                call_session_id=call_session_id,
                context_snippet=item.get("context_snippet", "") or "",
            )
        )
        touched_tools.append(tool)

    return len(touched_tools)


def _map_tech_scout_row(row: sqlite3.Row) -> Tool:
    """tech-scout's url/github_url/github_stars/language have no matching
    column here, so they're folded into description/tags instead of dropped."""
    description = row["description"] or ""
    link = row["github_url"] or row["url"] or ""
    if link:
        description = f"{description} ({link})".strip()

    tags = []
    if row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            tags = []
    if row["language"]:
        tags.append(row["language"])

    return Tool(
        id=None,
        name=row["name"],
        normalized_name=normalize_tool_name(row["name"]),
        category=row["category"] or "",
        description=description,
        summary=row["summary"] or "",
        tags=json.dumps(tags),
    )


def import_from_tech_scout(db_path: str) -> tuple[int, int]:
    """
    Import tools already saved in tech-scout's SQLite DB — a separate
    personal project with no per-call association — into this catalog.
    Never overwrites an existing tool's enrichment on a name collision.

    Returns (imported_count, skipped_count).
    """
    if not Path(db_path).exists():
        raise FileNotFoundError(db_path)

    src_conn = sqlite3.connect(db_path)
    src_conn.row_factory = sqlite3.Row
    try:
        rows = src_conn.execute("SELECT * FROM tools ORDER BY name").fetchall()
    finally:
        src_conn.close()

    imported: list[Tool] = []
    skipped = 0
    for row in rows:
        tool = _map_tech_scout_row(row)
        if find_tool_by_name(tool.name) is not None:
            skipped += 1
            continue
        imported.append(create_tool(tool))

    return len(imported), skipped


def save_researched_tool(
    name: str,
    *,
    category: str = "",
    description: str = "",
    summary: str = "",
    tags: list[str] | None = None,
    source_url: str = "",
) -> tuple[Tool, bool]:
    """
    Persist a tool record that's already been researched/structured upstream
    (e.g. by whichever LLM/agent an external caller like Hermes has
    configured) — this function only owns storage, it never fetches a URL
    or calls an LLM itself. Same dedup policy as
    ingest_tools()/import_from_tech_scout(): never overwrites an existing
    tool's enrichment on a name collision.

    Returns (tool, created) — created=False on a dedup hit.
    """
    name = name.strip()
    if not name:
        raise ValueError("name is required")

    existing = find_tool_by_name(name)
    if existing is not None:
        return existing, False

    full_description = description.strip()
    if source_url:
        full_description = f"{full_description} ({source_url})".strip()

    tool = create_tool(
        Tool(
            id=None,
            name=name,
            normalized_name=normalize_tool_name(name),
            category=category,
            description=full_description,
            summary=summary,
            tags=json.dumps(tags or []),
        )
    )
    return tool, True


async def search_tools(query: str) -> list[Tool]:
    """Case-insensitive substring search over the tools catalog by name."""
    needle = query.strip().lower()
    if not needle:
        return []
    return [t for t in get_tools() if needle in t.name.lower()]
