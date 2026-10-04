"""
Unit tests for PR2 — src/processing/tool_extractor.py.

TDD RED phase. All tests reference src/processing/tool_extractor.py which does
NOT exist yet (guarantees failure at import time).

Covers spec scenarios (sdd/tools-catalog, PR2 slice):
  Phase 6 — extraction LLM backend dispatch + JSON parsing (no chunk fallback)
  Phase 7 — ingest_tools() persistence: new tool, existing tool (dedup + remention),
            empty extraction result
  Phase 9 — search_tools() name-substring search
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


# ─────────────────────────────────────────────────────────────
# Phase 6 — _call_tools_llm backend dispatch + _parse_tools_response
# ─────────────────────────────────────────────────────────────

class TestCallToolsLlmBackendDispatch:
    def test_ollama_backend_used_by_default(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.processing import tool_extractor

        monkeypatch.delenv("LLM_BACKEND", raising=False)
        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"tools": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = tool_extractor._call_tools_llm("some transcript")

        assert result == '{"tools": []}'
        # ollama backend uses api_key="ollama" and a base_url kwarg
        _, kwargs = mock_openai_cls.call_args
        assert kwargs["api_key"] == "ollama"
        assert "base_url" in kwargs

    def test_gpt_backend_dispatches_to_openai(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.processing import tool_extractor

        monkeypatch.setenv("LLM_BACKEND", "gpt")
        mock_openai_cls = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content='{"tools": []}'))]
        mock_client.chat.completions.create.return_value = mock_resp
        mock_openai_cls.return_value = mock_client

        with patch.object(llm_backend.openai, "OpenAI", mock_openai_cls):
            result = tool_extractor._call_tools_llm("some transcript")

        assert result == '{"tools": []}'
        _, kwargs = mock_openai_cls.call_args
        assert kwargs["api_key"] != "ollama"

    def test_claude_backend_dispatches_to_anthropic(self, monkeypatch):
        from src.llm import backend as llm_backend
        from src.processing import tool_extractor

        monkeypatch.setenv("LLM_BACKEND", "claude")
        mock_anthropic_cls = MagicMock()
        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"tools": []}')]
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        with patch.object(llm_backend.anthropic, "Anthropic", mock_anthropic_cls):
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
# Phase 9 — search_tools() name-substring search
# ─────────────────────────────────────────────────────────────

class TestSearchTools:
    @pytest.mark.asyncio
    async def test_matches_case_insensitive_name_substring(self, patched_db, no_openai_key):
        from src.db.database import Tool
        from src.processing import tool_extractor

        t1 = patched_db.create_tool(Tool(id=None, name="Chroma", normalized_name="chroma"))
        patched_db.create_tool(Tool(id=None, name="Deepgram", normalized_name="deepgram"))

        results = await tool_extractor.search_tools("chr")

        assert [r.id for r in results] == [t1.id]

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_list(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        results = await tool_extractor.search_tools("nothing matches")

        assert results == []


# ─────────────────────────────────────────────────────────────
# import_from_tech_scout() — settings-triggered import from tech-scout's
# standalone tools.db (a separate personal project, no per-call association)
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def tech_scout_db(tmp_path):
    """A minimal tech-scout-shaped SQLite DB with 2 tools."""
    import sqlite3

    db_path = tmp_path / "tech_scout_tools.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE tools (
            id INTEGER PRIMARY KEY, name TEXT, url TEXT, github_url TEXT,
            category TEXT, description TEXT, summary TEXT,
            github_stars INTEGER, language TEXT, tags TEXT, created_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO tools (name, url, github_url, category, description, summary, "
        "github_stars, language, tags) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "ripgrep", None, "https://github.com/BurntSushi/ripgrep", "CLI",
            "Fast grep replacement", "Recursive regex search tool.",
            50000, "Rust", json.dumps(["cli", "search"]),
        ),
    )
    conn.execute(
        "INSERT INTO tools (name, url, github_url, category, description, summary, "
        "github_stars, language, tags) VALUES (?,?,?,?,?,?,?,?,?)",
        ("SuiteCRM", "https://suitecrm.com", None, "Platform", "Open source CRM", "", None, None, None),
    )
    conn.commit()
    conn.close()
    return db_path


class TestImportFromTechScout:
    def test_imports_all_rows_on_empty_catalog(self, patched_db, tech_scout_db, no_openai_key):
        from src.processing import tool_extractor

        imported, skipped = tool_extractor.import_from_tech_scout(str(tech_scout_db))

        assert imported == 2
        assert skipped == 0
        names = {t.name for t in patched_db.get_tools()}
        assert names == {"ripgrep", "SuiteCRM"}

    def test_github_url_and_language_folded_into_description_and_tags(
        self, patched_db, tech_scout_db, no_openai_key
    ):
        from src.processing import tool_extractor

        tool_extractor.import_from_tech_scout(str(tech_scout_db))

        rg = patched_db.find_tool_by_name("ripgrep")
        assert "github.com/BurntSushi/ripgrep" in rg.description
        assert "Rust" in json.loads(rg.tags)

    def test_existing_tool_is_skipped_not_duplicated(self, patched_db, tech_scout_db, no_openai_key):
        from src.processing import tool_extractor

        patched_db.create_tool(
            patched_db.Tool(
                id=None, name="ripgrep", normalized_name=patched_db.normalize_tool_name("ripgrep"),
                description="already enriched by a call mention",
            )
        )

        imported, skipped = tool_extractor.import_from_tech_scout(str(tech_scout_db))

        assert imported == 1
        assert skipped == 1
        rg = patched_db.find_tool_by_name("ripgrep")
        assert rg.description == "already enriched by a call mention"

    def test_missing_source_db_raises_file_not_found(self, patched_db):
        from src.processing import tool_extractor

        with pytest.raises(FileNotFoundError):
            tool_extractor.import_from_tech_scout(str(patched_db.DB_PATH.parent / "nope.db"))


# ─────────────────────────────────────────────────────────────
# save_researched_tool() — pure storage for a record already researched/
# structured upstream (e.g. by Hermes's own LLM/agent) — no fetch, no LLM.
# ─────────────────────────────────────────────────────────────

class TestSaveResearchedTool:
    def test_creates_new_tool_and_returns_created_true(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        tool, created = tool_extractor.save_researched_tool(
            "Chroma", category="Vector DB", description="Embedding database",
            summary="Used for RAG", tags=["vector", "rag"],
        )

        assert created is True
        assert tool.name == "Chroma"
        assert tool.normalized_name == "chroma"
        assert tool.category == "Vector DB"
        assert tool.summary == "Used for RAG"
        assert json.loads(tool.tags) == ["vector", "rag"]
        assert patched_db.get_tools() == [tool]

    def test_dedup_hit_returns_existing_and_never_overwrites(self, patched_db, no_openai_key):
        from src.db.database import Tool
        from src.processing import tool_extractor

        existing = patched_db.create_tool(
            Tool(id=None, name="Chroma", normalized_name="chroma",
                 description="Original description")
        )

        tool, created = tool_extractor.save_researched_tool(
            "Chroma", description="A different description",
        )

        assert created is False
        assert tool.id == existing.id
        assert tool.description == "Original description"
        assert len(patched_db.get_tools()) == 1

    def test_source_url_folded_into_description(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        tool, _ = tool_extractor.save_researched_tool(
            "ripgrep", description="Fast grep replacement",
            source_url="https://github.com/BurntSushi/ripgrep",
        )

        assert tool.description == (
            "Fast grep replacement (https://github.com/BurntSushi/ripgrep)"
        )

    def test_tags_default_to_empty_list_when_omitted(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        tool, _ = tool_extractor.save_researched_tool("SuiteCRM")

        assert json.loads(tool.tags) == []

    def test_empty_name_raises_value_error(self, patched_db, no_openai_key):
        from src.processing import tool_extractor

        with pytest.raises(ValueError):
            tool_extractor.save_researched_tool("   ")
