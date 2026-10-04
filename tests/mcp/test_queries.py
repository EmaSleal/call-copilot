"""
Unit tests for src/mcp/queries.py — pure, MCP-SDK-free read query logic
backing the read-only MCP server's `search_content` tool contract.

Spec scenarios covered (sdd/mcp-server-read-only/spec):
- Category filter scoping (parent includes children / subcategory exact)
- Category + technology combined (call source)
- Technology match via text fallback (video)
- Unknown technology returns empty, not an error
- No filters provided still returns a bounded (LIMIT-capped) result
"""

from pathlib import Path

import pytest


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_mcp_queries.db"


@pytest.fixture
def patched_db(db_path: Path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestResolveCategoryScope:
    def test_parent_category_includes_subcategory_ids(self, patched_db):
        from src.mcp.queries import resolve_category_scope

        backend = patched_db.create_category("Backend", "desc")
        databases = patched_db.create_category("Databases", "desc", parent_id=backend.id)

        scope = resolve_category_scope(backend.id)

        assert set(scope) == {backend.id, databases.id}

    def test_subcategory_id_scopes_to_exactly_itself(self, patched_db):
        from src.mcp.queries import resolve_category_scope

        backend = patched_db.create_category("Backend", "desc")
        databases = patched_db.create_category("Databases", "desc", parent_id=backend.id)

        scope = resolve_category_scope(databases.id)

        assert scope == [databases.id]
        assert backend.id not in scope

    def test_top_level_category_without_children_returns_itself_only(self, patched_db):
        from src.mcp.queries import resolve_category_scope

        solo = patched_db.create_category("Solo", "desc")

        assert resolve_category_scope(solo.id) == [solo.id]


def _seed_taxonomy(patched_db):
    """Backend (parent) > Databases (child), Frontend (sibling top-level)."""
    backend = patched_db.create_category("Backend", "desc")
    databases = patched_db.create_category("Databases", "desc", parent_id=backend.id)
    frontend = patched_db.create_category("Frontend", "desc")
    return backend, databases, frontend


def _make_tool(patched_db, name):
    from src.db.database import Tool
    return patched_db.create_tool(
        Tool(id=None, name=name, normalized_name=patched_db.normalize_tool_name(name))
    )


class TestSearchContentCategoryScoping:
    def test_parent_category_id_includes_subcategory_segments(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp.queries import search_content

        backend, databases, _frontend = _seed_taxonomy(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="db idea", category_id=databases.id)
        )

        results = search_content(category_id=backend.id)

        assert any(r["matched_text"] == "db idea" for r in results)

    def test_subcategory_id_excludes_siblings_parent_and_unclassified(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp.queries import search_content

        backend, databases, frontend = _seed_taxonomy(patched_db)
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="db idea", category_id=databases.id)
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=1, text="frontend idea", category_id=frontend.id)
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=2, text="backend unclassified", category_id=backend.id)
        )
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=3, text="no category at all", category_id=None)
        )

        results = search_content(category_id=databases.id)

        texts = {r["matched_text"] for r in results}
        assert texts == {"db idea"}


class TestSearchContentTechnologyFilter:
    def test_category_and_technology_combined_call_source(self, patched_db):
        from src.db.database import CallSegment, ToolMention
        from src.mcp.queries import search_content

        backend, databases, _frontend = _seed_taxonomy(patched_db)
        redis = _make_tool(patched_db, "Redis")

        matching_cs = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/a.txt", title="Redis call"
        )
        patched_db.save_call_segment(
            CallSegment(
                id=None, call_session_id=matching_cs.id, sort_order=0,
                text="usamos Redis para cache", category_id=databases.id,
            )
        )
        patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=redis.id, call_session_id=matching_cs.id, context_snippet="Redis")
        )

        # Same category, no tool mention -> must be excluded (AND semantics)
        other_cs = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/b.txt", title="Other call"
        )
        patched_db.save_call_segment(
            CallSegment(
                id=None, call_session_id=other_cs.id, sort_order=0,
                text="otra idea sin redis", category_id=databases.id,
            )
        )

        # Matching tool mention, but different category -> must be excluded
        frontend_cs = patched_db.create_call_session(
            context="ctx", transcript_path="whisper-text/c.txt", title="Frontend call"
        )
        patched_db.save_call_segment(
            CallSegment(
                id=None, call_session_id=frontend_cs.id, sort_order=0,
                text="usamos Redis en frontend", category_id=None,
            )
        )
        patched_db.save_tool_mention(
            ToolMention(id=None, tool_id=redis.id, call_session_id=frontend_cs.id, context_snippet="Redis")
        )

        results = search_content(category_id=backend.id, technology="Redis", source="call")

        assert len(results) == 1
        assert results[0]["matched_text"] == "usamos Redis para cache"
        assert results[0]["session_id"] == matching_cs.id

    def test_technology_matched_via_text_fallback_for_video(self, patched_db):
        from src.db.database import Segment
        from src.mcp.queries import search_content

        video_session = patched_db.create_video_session(title="Video 1", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0,
                    text="...usamos Redis para...")
        )

        results = search_content(technology="Redis", source="video")

        assert len(results) == 1
        assert results[0]["source"] == "video"
        assert "Redis" in results[0]["matched_text"]

    def test_technology_text_fallback_not_used_for_call_source_tool_mentions_only(self, patched_db):
        """A call segment whose text merely mentions the word must NOT match
        unless there's a curated tool_mention — the text fallback is video-only."""
        from src.db.database import CallSegment
        from src.mcp.queries import search_content

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="hablamos de Redis")
        )

        results = search_content(technology="Redis", source="call")

        assert results == []

    def test_unknown_technology_returns_empty_not_error(self, patched_db):
        from src.db.database import CallSegment, Segment
        from src.mcp.queries import search_content

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="usamos Postgres")
        )
        video_session = patched_db.create_video_session(title="Video 1", url="http://x")
        patched_db.save_segment(
            Segment(id=None, session_id=video_session.id, start_s=0.0, end_s=1.0, text="hablamos de Kafka")
        )

        results = search_content(technology="Cobol")

        assert results == []


class TestSearchContentDefaultBound:
    def test_no_filters_returns_bounded_default_not_unfiltered_scan(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp.queries import search_content, DEFAULT_LIMIT

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        for i in range(DEFAULT_LIMIT + 20):
            patched_db.save_call_segment(
                CallSegment(id=None, call_session_id=cs.id, sort_order=i, text=f"idea {i}")
            )

        results = search_content()

        assert len(results) == DEFAULT_LIMIT

    def test_limit_is_capped_at_200(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp.queries import search_content, MAX_LIMIT

        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        for i in range(MAX_LIMIT + 20):
            patched_db.save_call_segment(
                CallSegment(id=None, call_session_id=cs.id, sort_order=i, text=f"idea {i}")
            )

        results = search_content(limit=9999)

        assert len(results) == MAX_LIMIT

    def test_result_shape_has_required_display_fields(self, patched_db):
        from src.db.database import CallSegment
        from src.mcp.queries import search_content

        cat = patched_db.create_category("Cat", "desc", color="#abcdef")
        cs = patched_db.create_call_session(context="ctx", transcript_path="whisper-text/x.txt", title="Call 1")
        patched_db.save_call_segment(
            CallSegment(id=None, call_session_id=cs.id, sort_order=0, text="idea", category_id=cat.id)
        )

        results = search_content(text_query="idea")

        assert len(results) == 1
        row = results[0]
        for field in (
            "session_id", "source", "session_title", "category_id",
            "category_name", "category_color", "matched_text", "created_at",
        ):
            assert field in row
        assert row["session_id"] == cs.id
        assert row["source"] == "call"
        assert row["session_title"] == "Call 1"
        assert row["category_name"] == "Cat"
        assert row["category_color"] == "#abcdef"
