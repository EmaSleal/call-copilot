"""
Pure-function tests for CategoriesTab's hierarchy display helper.

`build_category_tree()` groups a flat `list[Category]` (as returned by
`db.get_categories()`) into parent-then-children display order, without any
Textual/DataTable dependency — mirrors the `_find_otro_category` precedent
in `src/tui/tabs/video.py`.
"""

from src.db.database import Category


class TestBuildCategoryTree:
    def test_top_level_only_categories_are_alphabetical_depth_zero(self):
        from src.tui.tabs.categories import build_category_tree

        cats = [
            Category(id=1, name="Zeta", description="", color="#000"),
            Category(id=2, name="Alfa", description="", color="#000"),
        ]

        result = build_category_tree(cats)

        assert result == [(cats[1], 0), (cats[0], 0)]

    def test_children_grouped_under_parent_alphabetically(self):
        from src.tui.tabs.categories import build_category_tree

        parent = Category(id=1, name="Diseño UI/UX", description="", color="#000")
        child_b = Category(id=2, name="Zebra", description="", color="#000", parent_id=1)
        child_a = Category(id=3, name="Tipografía", description="", color="#000", parent_id=1)
        cats = [child_b, parent, child_a]

        result = build_category_tree(cats)

        assert result == [(parent, 0), (child_a, 1), (child_b, 1)]

    def test_multiple_parents_each_keep_their_own_children(self):
        from src.tui.tabs.categories import build_category_tree

        parent1 = Category(id=1, name="Alfa", description="", color="#000")
        child1 = Category(id=2, name="Alfa Hijo", description="", color="#000", parent_id=1)
        parent2 = Category(id=3, name="Beta", description="", color="#000")
        child2 = Category(id=4, name="Beta Hijo", description="", color="#000", parent_id=3)
        cats = [child2, parent2, child1, parent1]

        result = build_category_tree(cats)

        assert result == [(parent1, 0), (child1, 1), (parent2, 0), (child2, 1)]

    def test_child_with_missing_parent_is_rendered_as_top_level(self):
        """Defensive: a child whose parent_id no longer matches any existing
        category (e.g. stale reference) must never be silently dropped."""
        from src.tui.tabs.categories import build_category_tree

        orphan = Category(id=5, name="Huérfana", description="", color="#000", parent_id=999)

        result = build_category_tree([orphan])

        assert result == [(orphan, 0)]

    def test_empty_list_returns_empty_list(self):
        from src.tui.tabs.categories import build_category_tree

        assert build_category_tree([]) == []
