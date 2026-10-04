"""Entrypoint for the read-only MCP server (`call-copilot-mcp` console
script — see `pyproject.toml`).

This is a separate stdio process; it does NOT inherit environment the way
the TUI's bootstrap does (`src/tui/app.py`, `main.py`), so `load_dotenv()`
runs at the very start of `main()`, before anything that might read an env
var (STT/LLM API keys are irrelevant here, but `src/core/paths.app_home()`
used by `src/db/database.py` can be env-configurable).

`load_dotenv()` is called with `env_store.ENV_PATH` explicitly rather than
its own default search — a bare `load_dotenv()` resolves via python-dotenv's
`find_dotenv()`, which walks up from the CALLING FILE's own location, not
from `app_home()`. For a pipx install launched by an external client
(Claude Desktop) from an unrelated cwd, that search never reaches
`~/.call-copilot/.env` — the exact file `src/core/env_store.py` (and the
TUI's settings screen) writes to. Confirmed empirically: `find_dotenv()`
returned `''` when run from `/tmp` against the installed package.

Deliberately does NOT import `src.tui.*` — this must stay a lightweight
process a client like Claude Desktop can launch on demand, not pull in
Textual.
"""

import os

from dotenv import load_dotenv

from src.core import env_store
from src.mcp import tools


def build_server():
    """Construct the MCP server instance and register every read-only tool.
    Split out from `main()` so task 2.7's manual verification (and any
    future in-process test) can introspect the registered tools without
    running the stdio transport."""
    from mcp.server import MCPServer

    server = MCPServer(
        name="call-copilot",
        title="call-copilot (read-only)",
        description=(
            "Read-only access to call-copilot's stored data: session "
            "history, categories, tools catalog, and content search over "
            "video/call transcripts."
        ),
    )

    server.add_tool(
        tools.search_content,
        name="search_content",
        description=(
            "Combinable search over video/call segments. Optional filters "
            "(category_id, technology, title_query, text_query, source) "
            "combine with AND; omitted filters are ignored. Always bounded "
            "by limit/offset (default limit 50, max 200) — never an "
            "unfiltered scan."
        ),
    )
    server.add_tool(
        tools.list_categories,
        name="list_categories",
        description=(
            "List the full category taxonomy (id, name, description, "
            "color, parent_id) so a client can pick a category_id for "
            "search_content and see which categories are subcategories."
        ),
    )
    server.add_tool(
        tools.list_tools_catalog,
        name="list_tools_catalog",
        description=(
            "List the Tools catalog, optionally filtered by a "
            "case-insensitive substring match on name."
        ),
    )
    server.add_tool(
        tools.search_tools_catalog,
        name="search_tools_catalog",
        description=(
            "Semantic (embedding-based) search over the Tools catalog — "
            "distinct from list_tools_catalog's literal substring filter. "
            "Best-effort: MAY return an empty list without OPENAI_API_KEY "
            "or chromadb; use list_tools_catalog for guaranteed results."
        ),
    )
    server.add_tool(
        tools.get_session,
        name="get_session",
        description=(
            "Get a unified session (video or call, by session_id + source) "
            "together with all of its segments in one call."
        ),
    )
    server.add_tool(
        tools.list_reports,
        name="list_reports",
        description=(
            "List video sessions that already have a generated HTML "
            "report, each with a file:// URL to open it directly. "
            "Optional case-insensitive substring filter on title. Skips "
            "reports whose file was deleted from disk."
        ),
    )
    server.add_tool(
        tools.get_report_url,
        name="get_report_url",
        description=(
            "Get the file:// URL for one video session's report by "
            "session_id, or null if it doesn't exist, has no report yet, "
            "or the file was deleted from disk."
        ),
    )
    server.add_tool(
        tools.semantic_search,
        name="semantic_search",
        description=(
            "Semantic (embedding-based) search across video and call "
            "segments. Optional and best-effort: it MAY return an empty "
            "list if this server's environment has no OPENAI_API_KEY or "
            "chromadb installed — an empty result does not mean the "
            "server is broken, it means semantic search is unavailable; "
            "use search_content for guaranteed full-text results."
        ),
    )
    # The server's one write surface — off by default. Approving/rejecting
    # only resolves a delete a human/agent already queued via
    # src/agent/commands.py (categories/tools catalog); it can never
    # originate a new delete. Set MCP_ALLOW_APPROVALS=true to opt in.
    if os.getenv("MCP_ALLOW_APPROVALS", "false").lower() == "true":
        server.add_tool(
            tools.approve_pending_action,
            name="approve_pending_action",
            description=(
                "Approve an agent-proposed pending delete (queued by "
                "call-copilot's own catalog-maintenance loop) and run it. "
                "Returns {'ok': False, 'error': ...} for an unknown or "
                "already-resolved pending_id instead of raising."
            ),
        )
        server.add_tool(
            tools.reject_pending_action,
            name="reject_pending_action",
            description=(
                "Reject an agent-proposed pending delete without running "
                "it. Returns {'ok': False, 'error': ...} for an unknown or "
                "already-resolved pending_id instead of raising."
            ),
        )
    # The server's second write surface — separate flag, separate risk
    # profile from MCP_ALLOW_APPROVALS: this originates NEW heavy work
    # (network download + CPU/GPU transcription, minutes) from an
    # arbitrary URL, rather than resolving a delete an internal agent
    # already vetted. Concurrency=1 is enforced atomically in
    # src/db/video_sessions.py::try_start_processing_session (validated
    # against real concurrent OS processes — see
    # docs/next-steps/feature-proposals.md point 5 Hallazgo 3). Off by
    # default; set MCP_ALLOW_VIDEO_PROCESSING=true to opt in.
    if os.getenv("MCP_ALLOW_VIDEO_PROCESSING", "false").lower() == "true":
        server.add_tool(
            tools.start_video_processing,
            name="start_video_processing",
            description=(
                "Start processing a video by URL (download, transcribe, "
                "classify, generate report) in the background — returns "
                "immediately with a session_id, never blocks until "
                "finished. Only one video may process at a time: returns "
                "{'ok': False, 'error': ...} if one is already running. "
                "Poll get_video_processing_status(session_id) for progress."
            ),
        )
        server.add_tool(
            tools.get_video_processing_status,
            name="get_video_processing_status",
            description=(
                "Poll the status of a video session (pending/processing/"
                "done/error), with report_url once done. Returns "
                "{'ok': False, 'error': ...} for an unknown session_id."
            ),
        )
    # The server's third write surface — separate flag: this persists a
    # tool record the CALLING AGENT already researched/structured with its
    # own LLM (call-copilot never fetches a URL or calls an LLM for this).
    # Never overwrites an existing tool's enrichment on a name collision.
    # Off by default; set MCP_ALLOW_TOOL_INGESTION=true to opt in.
    if os.getenv("MCP_ALLOW_TOOL_INGESTION", "false").lower() == "true":
        server.add_tool(
            tools.save_tool,
            name="save_tool",
            description=(
                "Persist a tool record already researched/structured by "
                "the calling agent's own LLM — this never fetches a URL "
                "or calls an LLM itself, only storage + semantic "
                "indexing. Never overwrites an existing tool's enrichment "
                "on a name collision (returns created=false instead). "
                "Returns {'ok': False, 'error': ...} for an empty name."
            ),
        )
    return server


def main() -> None:
    load_dotenv(env_store.ENV_PATH)
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
