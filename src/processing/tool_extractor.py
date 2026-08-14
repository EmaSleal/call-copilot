"""
Tools Catalog extraction for Call Copilot.

Identifies concrete named tools/products/libraries/platforms mentioned in a
call transcript, deduplicates them against the persistent tools catalog,
records a per-call mention, and (best-effort) embeds them into the semantic
store for later `search_tools()` lookups.

Supported LLM backends: ollama (default) | gpt | claude
  — mirrors the same backend-switch pattern as src/processing/session_processor.py.
"""

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path

import anthropic
import openai
from openai import AsyncOpenAI

from src.db.database import (
    Tool,
    ToolMention,
    create_tool,
    find_tool_by_name,
    get_tools_by_ids,
    normalize_tool_name,
    save_tool_mention,
)
from src.rag.tools_store import ToolsCatalogStore

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

    if backend == "claude":
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_TOOLS_SYSTEM,
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
                {"role": "system", "content": _TOOLS_SYSTEM},
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
            {"role": "system", "content": _TOOLS_SYSTEM},
            {"role": "user", "content": transcript},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


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


def _embedding_text(tool: Tool) -> str:
    """Build the text embedded into the semantic store for a tool."""
    parts = [tool.name]
    for field in (tool.category, tool.description, tool.summary, tool.tags):
        if field:
            parts.append(field)
    return ". ".join(parts)


def _build_openai_client() -> AsyncOpenAI | None:
    """Build an AsyncOpenAI client, or None when OPENAI_API_KEY is not configured."""
    api_key = os.getenv("OPENAI_API_KEY")
    return AsyncOpenAI(api_key=api_key) if api_key else None


async def _embed_tools(tools: list[Tool]) -> None:
    """Embed each touched tool into the semantic store. Best-effort — the store
    itself no-ops without an OpenAI client."""
    openai_client = _build_openai_client()
    store = ToolsCatalogStore(openai_client=openai_client)
    for tool in tools:
        await store.add_tool(tool.id, _embedding_text(tool))


def ingest_tools(call_session_id: int, spoken_text: str) -> int:
    """
    Extract concrete tools mentioned in spoken_text, dedup/persist them, record a
    mention for this call, and (best-effort) embed them into the semantic store.

    Extraction and SQLite persistence run regardless of LLM_BACKEND and regardless
    of OPENAI_API_KEY availability; only the Chroma embedding write is skipped
    without a configured OpenAI client.

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

    if touched_tools:
        asyncio.run(_embed_tools(touched_tools))

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

    if imported:
        asyncio.run(_embed_tools(imported))

    return len(imported), skipped


async def search_tools(query: str, top_k: int = 5) -> list[Tool]:
    """Semantic search over the tools catalog, joined back to full SQLite rows."""
    openai_client = _build_openai_client()
    store = ToolsCatalogStore(openai_client=openai_client)
    ranked = await store.search(query, top_k=top_k)
    ids = [tool_id for tool_id, _ in ranked]
    return get_tools_by_ids(ids)


async def answer_tools_query(query: str, top_k: int = 5) -> str:
    """Human-readable summary of the top matching tools for a query."""
    tools = await search_tools(query, top_k=top_k)
    if not tools:
        return "No matching tools found."

    lines = []
    for tool in tools:
        line = f"- {tool.name}"
        if tool.category:
            line += f" ({tool.category})"
        detail = tool.summary or tool.description
        if detail:
            line += f": {detail}"
        lines.append(line)
    return "\n".join(lines)
