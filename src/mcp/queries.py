"""Composed read-only queries for the MCP read API.

These queries are shaped by the MCP tool contract's combinable search
filters (sdd/mcp-server-read-only/spec) rather than by any TUI screen, so
they live here instead of growing `src/db/segments.py`. They reuse
`database._conn()` directly — the same connection primitive every DAO
module under `src/db/` already shares.
"""

from typing import Optional

from src.db import database
from src.db.tools import normalize_tool_name

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def resolve_category_scope(category_id: int) -> list[int]:
    """Expand a category id to itself plus its direct children, if any.

    Category nesting is single-level only — `_assert_valid_parent` in
    `src/db/categories.py` enforces this app-wide — so a flat lookup is
    sufficient and a recursive CTE would solve a problem that cannot occur.

    - Subcategory (row has a non-null `parent_id`): scope is exactly
      `[category_id]`.
    - Top-level category (no `parent_id`), or unknown id: scope is
      `[category_id, *child_ids]` (empty `child_ids` for a childless or
      unknown category collapses to just `[category_id]`).
    """
    with database._conn() as conn:
        row = conn.execute(
            "SELECT parent_id FROM categories WHERE id=? AND deleted_at IS NULL",
            (category_id,),
        ).fetchone()
        if row is not None and row["parent_id"] is not None:
            return [category_id]

        children = conn.execute(
            "SELECT id FROM categories WHERE parent_id=? AND deleted_at IS NULL",
            (category_id,),
        ).fetchall()
    return [category_id] + [c["id"] for c in children]


def _resolve_technology_call_session_ids(technology: str) -> list[int]:
    """Call session ids whose `tool_mentions` reference a tool matching
    `technology`, by case-insensitive normalized name or numeric tool id."""
    normalized = normalize_tool_name(technology)
    stripped = technology.strip()

    with database._conn() as conn:
        if stripped.isdigit():
            rows = conn.execute(
                """
                SELECT DISTINCT tm.call_session_id
                FROM tool_mentions tm
                JOIN tools t ON tm.tool_id = t.id
                WHERE (t.normalized_name = ? OR t.id = ?)
                  AND t.deleted_at IS NULL AND tm.deleted_at IS NULL
                """,
                (normalized, int(stripped)),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT DISTINCT tm.call_session_id
                FROM tool_mentions tm
                JOIN tools t ON tm.tool_id = t.id
                WHERE t.normalized_name = ?
                  AND t.deleted_at IS NULL AND tm.deleted_at IS NULL
                """,
                (normalized,),
            ).fetchall()
    return [r["call_session_id"] for r in rows]


def _technology_clause(technology: str, source: Optional[str]) -> tuple[str, list]:
    """Build the OR-ed technology sub-clause per source.

    - source == "call": curated tool_mentions match only.
    - source == "video": text LIKE fallback only (no tool_mentions data for
      video — an intentional, documented accuracy gap, not a bug).
    - source is None (unscoped): a segment matches if it satisfies EITHER
      branch, evaluated against its own source.

    Returns a `(sql_fragment, params)` pair. When no branch is applicable
    (e.g. source="call" but no catalog/mention match at all), the fragment
    is the always-false `"0=1"` so the caller gets an empty result instead
    of an error.
    """
    branches: list[str] = []
    params: list = []

    if source != "video":
        call_session_ids = _resolve_technology_call_session_ids(technology)
        if call_session_ids:
            placeholders = ",".join("?" for _ in call_session_ids)
            branches.append(f"(us.source = 'call' AND us.session_id IN ({placeholders}))")
            params.extend(call_session_ids)

    if source != "call":
        branches.append("(us.source = 'video' AND us.text LIKE ?)")
        params.append(f"%{technology}%")

    if not branches:
        return "0=1", []
    return "(" + " OR ".join(branches) + ")", params


def search_content(
    category_id: Optional[int] = None,
    technology: Optional[str] = None,
    title_query: Optional[str] = None,
    text_query: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> list[dict]:
    """Combinable AND search over `unified_segments`, joined to
    `unified_sessions` (title/created_at) and `categories` (name/color).

    All filters are optional and combine with AND when provided; an omitted
    filter is ignored, never treated as "match nothing". A LIMIT (capped at
    `MAX_LIMIT`, default `DEFAULT_LIMIT`) and OFFSET are always applied,
    even with zero filters, so this never becomes an unbounded scan.

    Returns dicts with: session_id, source, session_title, category_id,
    category_name, category_color, matched_text, created_at.
    """
    clauses: list[str] = []
    params: list = []

    if category_id is not None:
        scope = resolve_category_scope(category_id)
        placeholders = ",".join("?" for _ in scope)
        clauses.append(f"us.category_id IN ({placeholders})")
        params.extend(scope)

    if title_query:
        clauses.append("se.title LIKE ?")
        params.append(f"%{title_query}%")

    if text_query:
        clauses.append("us.text LIKE ?")
        params.append(f"%{text_query}%")

    if source:
        clauses.append("us.source = ?")
        params.append(source)

    if technology:
        tech_sql, tech_params = _technology_clause(technology, source)
        clauses.append(tech_sql)
        params.extend(tech_params)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    bounded_limit = max(1, min(limit, MAX_LIMIT))

    sql = f"""
        SELECT us.session_id AS session_id, us.source AS source,
               se.title AS session_title, us.category_id AS category_id,
               c.name AS category_name, c.color AS category_color,
               us.text AS matched_text, se.created_at AS created_at
        FROM unified_segments us
        JOIN unified_sessions se ON se.source = us.source AND se.id = us.session_id
        LEFT JOIN categories c ON c.id = us.category_id AND c.deleted_at IS NULL
        {where}
        ORDER BY se.created_at DESC, us.position
        LIMIT ? OFFSET ?
    """
    params.extend([bounded_limit, offset])

    with database._conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
