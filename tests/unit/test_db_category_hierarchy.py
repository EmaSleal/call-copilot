"""
Unit tests for single-level category hierarchy: `parent_id` migration,
create/update accepting `parent_id`, and `_assert_valid_parent` guards.

RED phase: `categories.parent_id` does not exist yet; create_category/
update_category do not accept a `parent_id` kwarg yet.
"""

import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "test_category_hierarchy.db"


@pytest.fixture
def patched_db(db_path, monkeypatch):
    import src.db.database as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


class TestParentIdColumn:
    def test_parent_id_column_exists_after_migrate(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        finally:
            conn.close()
        assert "parent_id" in col_names

    def test_parent_id_column_is_nullable(self, patched_db, db_path):
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("PRAGMA table_info(categories)").fetchall()
            parent_id_col = next(r for r in rows if r[1] == "parent_id")
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            assert parent_id_col[3] == 0, "parent_id must be nullable (notnull=0)"
        finally:
            conn.close()

    def test_migrate_is_idempotent_on_preexisting_db(self, patched_db, db_path):
        """Running init_db() again on a DB that already has parent_id must not raise."""
        import src.db.database as db_module
        db_module.init_db()
        conn = sqlite3.connect(db_path)
        try:
            col_names = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        finally:
            conn.close()
        assert "parent_id" in col_names


class TestCreateCategoryWithParentId:
    def test_create_subcategory_persists_parent_id(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)

        assert child.parent_id == parent.id

    def test_create_category_parent_id_defaults_to_none(self, patched_db):
        cat = patched_db.create_category("Standalone", "desc")

        assert cat.parent_id is None


class TestUpdateCategoryWithParentId:
    def test_update_category_sets_parent_id(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo")

        patched_db.update_category(child.id, "Tipografía", "desc hijo", "#6366f1", parent_id=parent.id)

        refreshed = {c.id: c for c in patched_db.get_categories()}
        assert refreshed[child.id].parent_id == parent.id

    def test_update_category_omitting_parent_id_clears_it(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)

        patched_db.update_category(child.id, "Tipografía", "desc hijo", "#6366f1")

        refreshed = {c.id: c for c in patched_db.get_categories()}
        assert refreshed[child.id].parent_id is None


class TestAssertValidParentRejectsInvalidNesting:
    def test_reject_self_parent_on_create_is_not_applicable(self, patched_db):
        # A category can't reference itself as parent at creation time (id doesn't
        # exist yet); self-parent only reachable via update. Covered below.
        pass

    def test_reject_self_parent_on_update(self, patched_db):
        cat = patched_db.create_category("Sola", "desc")

        with pytest.raises(ValueError):
            patched_db.update_category(cat.id, "Sola", "desc", "#6366f1", parent_id=cat.id)

    def test_reject_two_level_nesting_on_create(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)

        with pytest.raises(ValueError):
            patched_db.create_category("Nieto", "desc nieto", parent_id=child.id)

    def test_reject_two_level_nesting_on_update(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)
        other = patched_db.create_category("Otra", "desc otra")

        with pytest.raises(ValueError):
            patched_db.update_category(other.id, "Otra", "desc otra", "#6366f1", parent_id=child.id)

    def test_reject_giving_a_parent_to_a_category_that_has_children(self, patched_db):
        """A category that itself already has children can't be assigned a
        parent — doing so would create a 3-level chain via its own children."""
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")
        patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)
        other = patched_db.create_category("Otra", "desc otra")

        with pytest.raises(ValueError):
            patched_db.update_category(parent.id, "Diseño UI/UX", "desc padre", "#6366f1", parent_id=other.id)

    def test_valid_single_level_nesting_does_not_raise(self, patched_db):
        parent = patched_db.create_category("Diseño UI/UX", "desc padre")

        child = patched_db.create_category("Tipografía", "desc hijo", parent_id=parent.id)

        assert child.parent_id == parent.id
