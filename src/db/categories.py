"""DAOs — Categories."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import sqlite3

from src.db import database


@dataclass
class Category:
    id: Optional[int]
    name: str
    description: str
    color: str = "#6366f1"  # indigo por defecto
    parent_id: Optional[int] = None  # subcategoría de otra si no es None (un solo nivel)
    deleted_at: Optional[str] = None


def get_categories() -> list[Category]:
    with database._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM categories WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
    return [Category(**dict(r)) for r in rows]


def _assert_valid_parent(conn: sqlite3.Connection, cat_id: Optional[int], parent_id: Optional[int]) -> None:
    """Enforce single-level category nesting (spec: Reject two-level nesting).

    Raises ValueError when:
    - `parent_id == cat_id` (self-parent)
    - the target parent is itself a subcategory (has a non-null parent_id)
    - `cat_id` itself already has children (giving it a parent would create
      a 3-level chain through its own children)
    """
    if parent_id is None:
        return
    if cat_id is not None and parent_id == cat_id:
        raise ValueError("A category cannot be its own parent.")

    parent_row = conn.execute(
        "SELECT parent_id FROM categories WHERE id=? AND deleted_at IS NULL", (parent_id,)
    ).fetchone()
    if parent_row is not None and parent_row["parent_id"] is not None:
        raise ValueError("Cannot nest a subcategory under another subcategory (single-level only).")

    if cat_id is not None:
        has_children = conn.execute(
            "SELECT 1 FROM categories WHERE parent_id=? AND deleted_at IS NULL LIMIT 1", (cat_id,)
        ).fetchone()
        if has_children is not None:
            raise ValueError("Cannot assign a parent to a category that already has children.")


def create_category(
    name: str, description: str, color: str = "#6366f1", parent_id: Optional[int] = None
) -> Category:
    with database._conn() as conn:
        _assert_valid_parent(conn, None, parent_id)
        cur = conn.execute(
            "INSERT INTO categories (name, description, color, parent_id) VALUES (?,?,?,?)",
            (name, description, color, parent_id)
        )
        return Category(
            id=cur.lastrowid, name=name, description=description, color=color, parent_id=parent_id
        )


def update_category(
    cat_id: int, name: str, description: str, color: str, parent_id: Optional[int] = None
) -> None:
    """Omitting `parent_id` clears it (promotes the category to top-level)."""
    with database._conn() as conn:
        _assert_valid_parent(conn, cat_id, parent_id)
        conn.execute(
            "UPDATE categories SET name=?, description=?, color=?, parent_id=? WHERE id=?",
            (name, description, color, parent_id, cat_id)
        )


def delete_category(cat_id: int, actor: str = "human") -> None:
    with database._conn() as conn:
        # Desasignar segmentos/fragmentos que usaban esta categoría antes de borrar
        conn.execute("UPDATE segments SET category_id=NULL WHERE category_id=?", (cat_id,))
        conn.execute("UPDATE call_segments SET category_id=NULL WHERE category_id=?", (cat_id,))
        # Promover hijos a nivel superior en vez de cascadear el borrado (D2)
        conn.execute("UPDATE categories SET parent_id=NULL WHERE parent_id=?", (cat_id,))
        conn.execute(
            "UPDATE categories SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), cat_id),
        )
        database._write_audit_log(conn, actor, "delete_category", "categories", cat_id)
