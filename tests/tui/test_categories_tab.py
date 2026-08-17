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


class TestParentSelectOptions:
    """Options for the `Select(id="cat-parent")` picker: top-level-only,
    excluding the category currently being edited (spec: Reject two-level
    nesting is enforced by the DAO; the picker only OFFERS valid targets)."""

    def test_only_top_level_categories_are_offered(self):
        from src.tui.tabs.categories import parent_select_options

        parent = Category(id=1, name="Diseño UI/UX", description="", color="#000")
        child = Category(id=2, name="Tipografía", description="", color="#000", parent_id=1)

        options = parent_select_options([parent, child], editing_id=None)

        assert options == [("Diseño UI/UX", 1)]

    def test_excludes_the_category_being_edited(self):
        from src.tui.tabs.categories import parent_select_options

        a = Category(id=1, name="Alfa", description="", color="#000")
        b = Category(id=2, name="Beta", description="", color="#000")

        options = parent_select_options([a, b], editing_id=1)

        assert options == [("Beta", 2)]

    def test_new_category_excludes_nothing(self):
        from src.tui.tabs.categories import parent_select_options

        a = Category(id=1, name="Alfa", description="", color="#000")

        options = parent_select_options([a], editing_id=None)

        assert options == [("Alfa", 1)]

    def test_empty_categories_returns_empty_options(self):
        from src.tui.tabs.categories import parent_select_options

        assert parent_select_options([], editing_id=None) == []


class TestHasChildren:
    def test_true_when_category_has_children(self):
        from src.tui.tabs.categories import has_children

        parent = Category(id=1, name="Diseño UI/UX", description="", color="#000")
        child = Category(id=2, name="Tipografía", description="", color="#000", parent_id=1)

        assert has_children([parent, child], 1) is True

    def test_false_when_category_has_no_children(self):
        from src.tui.tabs.categories import has_children

        parent = Category(id=1, name="Diseño UI/UX", description="", color="#000")

        assert has_children([parent], 1) is False

    def test_false_for_empty_categories(self):
        from src.tui.tabs.categories import has_children

        assert has_children([], 1) is False


class TestFormatCategoryRow:
    """Indented `└─` rows for the grouped list (spec: Grouped list)."""

    def test_depth_zero_is_the_plain_name(self):
        from src.tui.tabs.categories import format_category_row

        cat = Category(id=1, name="Diseño UI/UX", description="", color="#000")

        assert format_category_row(cat, 0) == "Diseño UI/UX"

    def test_depth_one_is_indented_with_corner_marker(self):
        from src.tui.tabs.categories import format_category_row

        cat = Category(id=2, name="Tipografía", description="", color="#000", parent_id=1)

        assert format_category_row(cat, 1) == "└─ Tipografía"


class TestColorSwatch:
    """Color column renders an actual swatch block instead of a raw hex
    string, so categories are recognizable at a glance."""

    def test_valid_hex_color_is_used_as_the_swatch_style(self):
        from src.tui.tabs.categories import color_swatch

        text = color_swatch("#6366f1")
        assert text.spans[0].style.color.name == "#6366f1"

    def test_valid_hex_color_text_includes_the_hex_code(self):
        from src.tui.tabs.categories import color_swatch

        text = color_swatch("#6366f1")
        assert "#6366f1" in text.plain

    def test_invalid_color_falls_back_instead_of_raising(self):
        from src.tui.tabs.categories import color_swatch

        text = color_swatch("not-a-color")
        assert text.spans[0].style.color.name == "grey50"


class TestCategoryRowCells:
    """Full DataTable row (id, name, color swatch, description) for one
    category — subcategory rows (depth 1) render dimmed so the hierarchy
    reads at a glance."""

    def test_top_level_row_is_not_dimmed(self):
        from src.tui.tabs.categories import category_row_cells

        cat = Category(id=1, name="Diseño", description="d", color="#6366f1")
        id_cell, name_cell, color_cell, desc_cell = category_row_cells(cat, 0)

        assert id_cell.plain == "1"
        assert name_cell.plain == "Diseño"
        assert "dim" not in str(id_cell.spans)
        assert "dim" not in str(name_cell.spans)

    def test_subcategory_row_is_dimmed(self):
        from src.tui.tabs.categories import category_row_cells

        cat = Category(id=2, name="Tipografía", description="d", color="#6366f1", parent_id=1)
        id_cell, name_cell, color_cell, desc_cell = category_row_cells(cat, 1)

        assert name_cell.plain == "└─ Tipografía"
        assert any("dim" in str(span.style) for span in id_cell.spans)
        assert any("dim" in str(span.style) for span in name_cell.spans)
        assert any("dim" in str(span.style) for span in color_cell.spans)
        assert any("dim" in str(span.style) for span in desc_cell.spans)

    def test_description_is_truncated_to_40_chars(self):
        from src.tui.tabs.categories import category_row_cells

        cat = Category(id=1, name="X", description="y" * 100, color="#6366f1")
        _id, _name, _color, desc_cell = category_row_cells(cat, 0)

        assert len(desc_cell.plain) == 40


class TestSaveCategoryFeedback:
    """DAO `ValueError` surfaced as feedback instead of crashing the TUI
    (design A3: single-level enforcement lives in the DAO)."""

    def test_create_success_returns_green_feedback_and_the_saved_category(self, spanish):
        from src.tui.tabs.categories import save_category_feedback

        cat = Category(id=1, name="Marketing", description="d", color="#000")
        success, message, saved = save_category_feedback(False, lambda: cat)

        assert success is True
        assert message == "[green]Categoría creada.[/green]"
        assert saved is cat

    def test_create_success_english(self, english):
        from src.tui.tabs.categories import save_category_feedback

        cat = Category(id=1, name="Marketing", description="d", color="#000")
        success, message, saved = save_category_feedback(False, lambda: cat)

        assert success is True
        assert message == "[green]Category created.[/green]"
        assert saved is cat

    def test_update_success_returns_green_feedback_with_updated_wording(self, spanish):
        from src.tui.tabs.categories import save_category_feedback

        cat = Category(id=1, name="Marketing", description="d", color="#000")
        success, message, saved = save_category_feedback(True, lambda: cat)

        assert success is True
        assert message == "[green]Categoría actualizada.[/green]"
        assert saved is cat

    def test_update_success_english(self, english):
        from src.tui.tabs.categories import save_category_feedback

        cat = Category(id=1, name="Marketing", description="d", color="#000")
        success, message, saved = save_category_feedback(True, lambda: cat)

        assert success is True
        assert message == "[green]Category updated.[/green]"
        assert saved is cat

    def test_dao_value_error_is_caught_and_surfaced_as_red_feedback(self):
        from src.tui.tabs.categories import save_category_feedback

        def raise_value_error():
            raise ValueError("Cannot nest a subcategory under another subcategory (single-level only).")

        success, message, saved = save_category_feedback(True, raise_value_error)

        assert success is False
        assert message == "[red]Cannot nest a subcategory under another subcategory (single-level only).[/red]"
        assert saved is None
