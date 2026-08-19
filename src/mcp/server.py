"""Entrypoint for the read-only MCP server (`call-copilot-mcp` console
script — see `pyproject.toml`).

This is a separate stdio process; it does NOT inherit environment the way
the TUI's bootstrap does (`src/tui/app.py`, `main.py`), so `load_dotenv()`
runs at the very start of `main()`, before anything that might read an env
var (STT/LLM API keys are irrelevant here, but `src/core/paths.app_home()`
used by `src/db/database.py` can be env-configurable).

Deliberately does NOT import `src.tui.*` — this must stay a lightweight
process a client like Claude Desktop can launch on demand, not pull in
Textual.
"""

from dotenv import load_dotenv

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
        tools.get_session,
        name="get_session",
        description=(
            "Get a unified session (video or call, by session_id + source) "
            "together with all of its segments in one call."
        ),
    )
    return server


def main() -> None:
    load_dotenv()
    server = build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
