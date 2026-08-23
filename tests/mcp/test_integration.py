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
    def test_server_lists_read_only_tools_by_default(self, monkeypatch):
        """MCP_ALLOW_APPROVALS/MCP_ALLOW_VIDEO_PROCESSING are off by
        default — the server's two write surfaces must not even be
        discoverable without opting in."""
        monkeypatch.delenv("MCP_ALLOW_APPROVALS", raising=False)
        monkeypatch.delenv("MCP_ALLOW_VIDEO_PROCESSING", raising=False)
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

    def test_server_adds_approval_tools_when_explicitly_enabled(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_APPROVALS", "true")
        from src.mcp.server import build_server

        server = build_server()
        registered = asyncio.run(server.list_tools())
        names = {tool.name for tool in registered}

        assert "approve_pending_action" in names
        assert "reject_pending_action" in names

    def test_server_keeps_approval_tools_off_for_any_other_value(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_APPROVALS", "1")
        from src.mcp.server import build_server

        server = build_server()
        registered = asyncio.run(server.list_tools())
        names = {tool.name for tool in registered}

        assert "approve_pending_action" not in names
        assert "reject_pending_action" not in names

    def test_server_adds_video_processing_tools_when_explicitly_enabled(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_VIDEO_PROCESSING", "true")
        from src.mcp.server import build_server

        server = build_server()
        registered = asyncio.run(server.list_tools())
        names = {tool.name for tool in registered}

        assert "start_video_processing" in names
        assert "get_video_processing_status" in names

    def test_server_keeps_video_processing_tools_off_for_any_other_value(self, monkeypatch):
        monkeypatch.setenv("MCP_ALLOW_VIDEO_PROCESSING", "1")
        from src.mcp.server import build_server

        server = build_server()
        registered = asyncio.run(server.list_tools())
        names = {tool.name for tool in registered}

        assert "start_video_processing" not in names
        assert "get_video_processing_status" not in names

    def test_both_write_flags_are_independent(self, monkeypatch):
        """Enabling one write surface must not enable the other."""
        monkeypatch.setenv("MCP_ALLOW_APPROVALS", "true")
        monkeypatch.delenv("MCP_ALLOW_VIDEO_PROCESSING", raising=False)
        from src.mcp.server import build_server

        server = build_server()
        names = {tool.name for tool in asyncio.run(server.list_tools())}

        assert "approve_pending_action" in names
        assert "start_video_processing" not in names
