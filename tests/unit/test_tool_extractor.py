"""
Unit tests for PR2 — src/processing/tool_extractor.py.

TDD RED phase. All tests reference src/processing/tool_extractor.py which does
NOT exist yet (guarantees failure at import time).

Covers spec scenarios (sdd/tools-catalog, PR2 slice):
  Phase 6 — extraction LLM backend dispatch + JSON parsing (no chunk fallback)
  Phase 7 — ingest_tools() persistence: new tool, existing tool (dedup + remention),
            empty extraction result
  Phase 8 — embedding wiring: asyncio.run bridge to ToolsCatalogStore.add_tool,
            backend independence (persistence works without OPENAI_API_KEY)
  Phase 9 — search_tools() / answer_tools_query()
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    """Isolated in-memory DB for each test."""
    import src.db.database as db_module
    db_path = tmp_path / "test_tool_extractor.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


@pytest.fixture
def no_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")


# ─────────────────────────────────────────────────────────────
# Phase 6 — _call_tools_llm backend dispatch + _parse_tools_response
# ─────────────────────────────────────────────────────────────

class TestCallToolsLlmBackendDispatch:
    def test_ollama_backend_used_by_default(self, monkeypatch):
        from src.processing import tool_extractor

        monkeypatch.delenv("LLM_BACKEND", raising=False)
        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"tools": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(tool_extractor.openai, "OpenAI", mock_openai_cls):
            result = tool_extractor._call_tools_llm("some transcript")

        assert result == '{"tools": []}'
        # ollama backend uses api_key="ollama" and a base_url kwarg
        _, kwargs = mock_openai_cls.call_args
        assert kwargs["api_key"] == "ollama"
        assert "base_url" in kwargs

    def test_gpt_backend_dispatches_to_openai(self, monkeypatch):
        from src.processing import tool_extractor

        monkeypatch.setenv("LLM_BACKEND", "gpt")
        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"tools": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(tool_extractor.openai, "OpenAI", mock_openai_cls):
            result = tool_extractor._call_tools_llm("some transcript")

        assert result == '{"tools": []}'
        _, kwargs = mock_openai_cls.call_args
        assert kwargs["api_key"] != "ollama"

    def test_claude_backend_dispatches_to_anthropic(self, monkeypatch):
        from src.processing import tool_extractor

        monkeypatch.setenv("LLM_BACKEND", "claude")
        mock_anthropic_cls = MagicMock()
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"tools": []}')]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        with patch.object(tool_extractor.anthropic, "Anthropic", mock_anthropic_cls):
            result = tool_extractor._call_tools_llm("some transcript")

        assert result == '{"tools": []}'
        mock_client.messages.create.assert_called_once()


class TestParseToolsResponse:
    def test_invalid_json_returns_empty_list(self):
        from src.processing import tool_extractor

        assert tool_extractor._parse_tools_response("NOT_VALID_JSON{{{{") == []

    def test_non_string_input_returns_empty_list(self):
        from src.processing import tool_extractor

        assert tool_extractor._parse_tools_response(MagicMock()) == []

    def test_valid_json_returns_list_of_dicts(self):
        from src.processing import tool_extractor

        raw = json.dumps({
            "tools": [
                {"name": "Chroma", "category": "Vector DB", "description": "desc",
                 "summary": "sum", "tags": "db", "context_snippet": "we used Chroma"},
            ]
        })
        result = tool_extractor._parse_tools_response(raw)
        assert isinstance(result, list)
        assert result[0]["name"] == "Chroma"

    def test_missing_tools_key_returns_empty_list(self):
        from src.processing import tool_extractor

        assert tool_extractor._parse_tools_response(json.dumps({"other": []})) == []

    def test_tools_key_not_a_list_returns_empty_list(self):
        from src.processing import tool_extractor

        assert tool_extractor._parse_tools_response(json.dumps({"tools": "oops"})) == []


# ─────────────────────────────────────────────────────────────
# Phase 7 — ingest_tools() persistence: new / existing / empty
# ─────────────────────────────────────────────────────────────

class TestIngestToolsNewTool:
    def test_new_tool_creates_one_tool_and_one_mention_row(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        raw = json.dumps({
            "tools": [
                {"name": "Deepgram", "category": "STT", "description": "Speech-to-text API",
                 "summary": "Used for live transcription", "tags": "stt,api",
                 "context_snippet": "we're using Deepgram for STT"},
            ]
        })

        with patch.object(tool_extractor, "_call_tools_llm", return_value=raw):
            touched = tool_extractor.ingest_tools(call_session_id=1, spoken_text="transcript text")

        assert touched == 1
        tools = patched_db.get_tools()
        assert len(tools) == 1
        assert tools[0].name == "Deepgram"
        assert tools[0].normalized_name == "deepgram"

        mentions = patched_db.get_tool_mentions(tools[0].id)
        assert len(mentions) == 1
        assert mentions[0].call_session_id == 1


class TestIngestToolsExistingTool:
    def test_existing_normalized_name_dedups_no_new_tool_row(self, patched_db, no_openai_key):
        from src.db.database import Tool
        from src.processing import tool_extractor

        existing = patched_db.create_tool(
            Tool(id=None, name="Chroma", normalized_name="chroma",
                 description="Original description")
        )

        raw = json.dumps({
            "tools": [
                {"name": "Chroma", "category": "Vector DB", "description": "New description",
                 "summary": "call summary", "tags": "", "context_snippet": "mentioned Chroma again"},
            ]
        })

        with patch.object(tool_extractor, "_call_tools_llm", return_value=raw):
            touched = tool_extractor.ingest_tools(call_session_id=2, spoken_text="transcript text")

        assert touched == 1
        tools = patched_db.get_tools()
        assert len(tools) == 1
        assert tools[0].id == existing.id
        # Existing enrichment must NOT be overwritten.
        assert tools[0].description == "Original description"

        mentions = patched_db.get_tool_mentions(existing.id)
        assert len(mentions) == 1
        assert mentions[0].call_session_id == 2


class TestIngestToolsEmptyResult:
    def test_zero_extracted_tools_writes_no_rows_no_error(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        raw = json.dumps({"tools": []})

        with patch.object(tool_extractor, "_call_tools_llm", return_value=raw):
            touched = tool_extractor.ingest_tools(call_session_id=1, spoken_text="nothing tool-related here")

        assert touched == 0
        assert patched_db.get_tools() == []

    def test_invalid_json_writes_no_rows_no_error(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        with patch.object(tool_extractor, "_call_tools_llm", return_value="NOT VALID JSON"):
            touched = tool_extractor.ingest_tools(call_session_id=1, spoken_text="irrelevant")

        assert touched == 0
        assert patched_db.get_tools() == []


# ─────────────────────────────────────────────────────────────
# Phase 8 — embedding wiring & backend independence
# ─────────────────────────────────────────────────────────────

class TestIngestToolsEmbeddingWiring:
    def test_add_tool_called_via_asyncio_run_when_client_present(
        self, patched_db, with_openai_key
    ):
        from src.processing import tool_extractor

        raw = json.dumps({
            "tools": [{"name": "Chroma", "category": "Vector DB", "description": "",
                       "summary": "", "tags": "", "context_snippet": ""}]
        })

        mock_store = MagicMock()
        mock_store.add_tool = AsyncMock(return_value=True)
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(tool_extractor, "_call_tools_llm", return_value=raw):
            with patch.object(tool_extractor, "ToolsCatalogStore", mock_store_cls):
                touched = tool_extractor.ingest_tools(call_session_id=1, spoken_text="text")

        assert touched == 1
        mock_store.add_tool.assert_awaited_once()
        args, _ = mock_store.add_tool.call_args
        tools = patched_db.get_tools()
        assert args[0] == tools[0].id

    def test_ollama_backend_without_openai_key_still_persists(
        self, patched_db, no_openai_key, monkeypatch
    ):
        """LLM_BACKEND=ollama + no OPENAI_API_KEY: tools/tool_mentions still persist,
        only the embedding step is skipped."""
        from src.processing import tool_extractor

        monkeypatch.setenv("LLM_BACKEND", "ollama")
        raw = json.dumps({
            "tools": [{"name": "Deepgram", "category": "STT", "description": "",
                       "summary": "", "tags": "", "context_snippet": ""}]
        })

        with patch.object(tool_extractor, "_call_tools_llm", return_value=raw):
            touched = tool_extractor.ingest_tools(call_session_id=1, spoken_text="text")

        assert touched == 1
        tools = patched_db.get_tools()
        assert len(tools) == 1
        assert tools[0].name == "Deepgram"


class TestBuildOpenaiClient:
    def test_no_key_returns_none(self, no_openai_key):
        from src.processing import tool_extractor

        assert tool_extractor._build_openai_client() is None

    def test_with_key_returns_client(self, with_openai_key):
        from src.processing import tool_extractor

        client = tool_extractor._build_openai_client()
        assert client is not None


# ─────────────────────────────────────────────────────────────
# Phase 9 — search_tools() / answer_tools_query()
# ─────────────────────────────────────────────────────────────

class TestSearchTools:
    @pytest.mark.asyncio
    async def test_search_tools_ranks_via_store_and_joins_sqlite_rows(
        self, patched_db, with_openai_key
    ):
        from src.db.database import Tool
        from src.processing import tool_extractor

        t1 = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma",
                                          description="Vector search engine"))
        t2 = patched_db.create_tool(Tool(id=None, name="Deepgram", normalized_name="deepgram"))

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[(t1.id, 0.1), (t2.id, 0.5)])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(tool_extractor, "ToolsCatalogStore", mock_store_cls):
            results = await tool_extractor.search_tools("vector database")

        assert [r.id for r in results] == [t1.id, t2.id]
        assert results[0].name == "Chroma"

    @pytest.mark.asyncio
    async def test_search_tools_empty_store_result_returns_empty_list(
        self, patched_db, with_openai_key
    ):
        from src.processing import tool_extractor

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(tool_extractor, "ToolsCatalogStore", mock_store_cls):
            results = await tool_extractor.search_tools("nothing matches")

        assert results == []


class TestAnswerToolsQuery:
    @pytest.mark.asyncio
    async def test_answer_tools_query_returns_readable_summary(self, patched_db, with_openai_key):
        from src.db.database import Tool
        from src.processing import tool_extractor

        t1 = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma",
                                          category="Vector DB", summary="Used for RAG"))

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[(t1.id, 0.1)])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(tool_extractor, "ToolsCatalogStore", mock_store_cls):
            answer = await tool_extractor.answer_tools_query("vector database")

        assert "Chroma" in answer

    @pytest.mark.asyncio
    async def test_answer_tools_query_no_matches_returns_message(self, patched_db, with_openai_key):
        from src.processing import tool_extractor

        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[])
        mock_store_cls = MagicMock(return_value=mock_store)

        with patch.object(tool_extractor, "ToolsCatalogStore", mock_store_cls):
            answer = await tool_extractor.answer_tools_query("nothing matches")

        assert answer
        assert "Chroma" not in answer
