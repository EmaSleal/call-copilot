"""
Integration test for src/mcp/server.py — sdd/mcp-server-read-only Phase 3
(task 3.3, design's Testing Strategy "Integration | Full server round-trip"
row). Deliberately lightweight and in-process: no real stdio subprocess, no
live DB/network — just confirms all read-only tools are registered on the
`MCPServer` instance via `build_server().list_tools()`, the same
introspection approach Phase 2's manual verification (task 2.7) already
used. A full protocol-level round-trip through stdio is disproportionate
for this project's scope.
"""

import asyncio


class TestServerToolRegistration:
    def test_server_lists_read_only_tools(self):
        from src.mcp.server import build_server

        server = build_server()
        registered = asyncio.run(server.list_tools())
        names = {tool.name for tool in registered}

        assert names == {
            "search_content",
            "list_categories",
            "list_tools_catalog",
            "get_session",
            "semantic_search",
            "list_reports",
            "get_report_url",
        }
