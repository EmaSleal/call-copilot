"""Tab 4: Categorías — CRUD de taxonomía."""

from typing import Optional

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, TabbedContent, TabPane

import src.db.database as db
from src.db.database import Category
from src.i18n import t
from src.processing.category_dedup import forget_category_embedding, sync_category_embedding

_SWATCH_BLOCK = "████ "
_FALLBACK_SWATCH_COLOR = "grey50"


def build_category_tree(categories: list[Category]) -> list[tuple[Category, int]]:
    """Display order [(category, depth)]: top-level alphabetical, children
    alphabetical under their parent. A child whose parent is missing is
    rendered as top-level (defensive, never dropped).

    Pure function — no side effects, easy to test without Textual. Mirrors
    the `_find_otro_category` precedent in `src/tui/tabs/video.py`.
    """
    by_id = {c.id: c for c in categories}
    children_by_parent: dict[int, list[Category]] = {}
    top_level: list[Category] = []

    for c in categories:
        if c.parent_id is not None and c.parent_id in by_id:
            children_by_parent.setdefault(c.parent_id, []).append(c)
        else:
            top_level.append(c)

    top_level.sort(key=lambda c: c.name)
    result: list[tuple[Category, int]] = []
    for parent in top_level:
        result.append((parent, 0))
        for child in sorted(children_by_parent.get(parent.id, []), key=lambda c: c.name):
            result.append((child, 1))
    return result


def parent_select_options(
    categories: list[Category], editing_id: Optional[int]
) -> list[tuple[str, int]]:
    """Options for `Select(id="cat-parent")`: top-level-only (single-level
    hierarchy, design A1/A3), excluding the category currently being edited
    (a category cannot be its own parent). `editing_id=None` for a new
    category excludes nothing.

    Pure function — no side effects, easy to test without Textual.
    """
    return [
        (c.name, c.id)
        for c in categories
        if c.parent_id is None and c.id != editing_id
    ]


def has_children(categories: list[Category], cat_id: int) -> bool:
    """True when `cat_id` is the parent of at least one other category —
    used to disable the parent picker while editing it (a category that
    already has children cannot itself become a subcategory, design A3).

    Pure function — no side effects, easy to test without Textual.
    """
    return any(c.parent_id == cat_id for c in categories)


def format_category_row(category: Category, depth: int) -> str:
    """Display label for a `build_category_tree()` row: depth 0 is the
    plain name, depth 1 (a subcategory) is indented with a corner marker
    (spec: Grouped list).

    Pure function — no side effects, easy to test without Textual.
    """
    return f"└─ {category.name}" if depth else category.name


def color_swatch(color: str) -> Text:
    """Colored block + hex code for the Color column, so a category's
    color reads at a glance instead of as a raw hex string. Falls back to
    a neutral gray block for a malformed color (e.g. a stray value from a
    hand-edited .env/DB row) instead of letting Rich raise on an invalid
    Style and crash the DataTable render.

    Pure function — no side effects, easy to test without Textual.
    """
    try:
        style = Style(color=color)
    except Exception:
        style = Style(color=_FALLBACK_SWATCH_COLOR)
    text = Text()
    text.append(_SWATCH_BLOCK, style=style)
    text.append(color)
    return text


def category_row_cells(category: Category, depth: int) -> tuple[Text, Text, Text, Text]:
    """Build one DataTable row (id, name, color swatch, description) for
    `build_category_tree()`'s grouped list. Subcategory rows (depth 1)
    render dimmed — the hierarchy is capped at one level (design A3), so
    dimming reads clearly at a glance without needing deeper indentation.

    Pure function — no side effects, easy to test without Textual.
    """
    id_cell = Text(str(category.id))
    name_cell = Text(format_category_row(category, depth))
    color_cell = color_swatch(category.color)
    desc_cell = Text(category.description[:40])
    if depth:
        for cell in (id_cell, name_cell, color_cell, desc_cell):
            cell.stylize("dim")
    return id_cell, name_cell, color_cell, desc_cell


def save_category_feedback(is_edit: bool, save_fn) -> tuple[bool, str, Optional[Category]]:
    """Invoke `save_fn()` — a zero-arg callable already bound to
    `db.create_category(...)`/`db.update_category(...)` args, returning the
    resulting `Category`. Catches the DAO's single-level-hierarchy
    `ValueError` guard (design A3) and surfaces it as feedback instead of
    letting it propagate and crash the TUI (spec: DAO ValueError surfaced
    as feedback). Returns `(success, feedback_markup, saved_category)`.

    Pure function — no side effects beyond calling `save_fn()`, easy to
    test without Textual.
    """
    try:
        saved = save_fn()
    except ValueError as e:
        return False, f"[red]{e}[/red]", None
    message = (
        f"[green]{t('categories.updated_feedback')}[/green]"
        if is_edit
        else f"[green]{t('categories.created_feedback')}[/green]"
    )
    return True, message, saved


class CategoriesTab(TabPane):
    def __init__(self):
        super().__init__(t("categories.tab_title"), id="tab-categories")
        self._selected_id = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="cat-layout"):
            with Vertical(id="cat-list-panel"):
                yield Label(t("categories.existing_label"), id="lbl-cat-existing")
                yield DataTable(id="cat-table")
                with Horizontal():
                    yield Button(t("categories.new_button"), id="btn-new-cat", variant="success")
                    yield Button(
                        t("categories.edit_button"), id="btn-edit-cat", variant="default", disabled=True
                    )
                    yield Button(
                        t("categories.delete_button"), id="btn-delete-cat", variant="error", disabled=True
                    )
            with Vertical(id="cat-form-panel"):
                yield Label(t("categories.name_label"), id="lbl-cat-name")
                yield Input(id="cat-name", placeholder=t("categories.name_placeholder"))
                yield Label(t("categories.description_label"), id="lbl-cat-desc")
                yield Input(id="cat-desc", placeholder=t("categories.description_placeholder"))
                yield Label(t("categories.color_label"), id="lbl-cat-color")
                yield Input(id="cat-color", placeholder="#6366f1", value="#6366f1")
                yield Label(t("categories.parent_label"), id="lbl-cat-parent")
                yield Select(
                    [],
                    id="cat-parent",
                    allow_blank=True,
                    prompt=t("categories.parent_prompt"),
                )
                with Horizontal():
                    yield Button(t("categories.save_button"), id="btn-save-cat", variant="primary")
                    yield Button(t("categories.cancel_button"), id="btn-cancel-cat", variant="default")
                yield Label("", id="cat-feedback")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome — not the DataTable's row data
        (category names are user data) and not the feedback line (result
        state, retranslated the next time it's set)."""
        self.query_one("#lbl-cat-existing", Label).update(t("categories.existing_label"))
        self.query_one("#btn-new-cat", Button).label = t("categories.new_button")
        self.query_one("#btn-edit-cat", Button).label = t("categories.edit_button")
        self.query_one("#btn-delete-cat", Button).label = t("categories.delete_button")
        self.query_one("#lbl-cat-name", Label).update(t("categories.name_label"))
        name_input = self.query_one("#cat-name", Input)
        if not name_input.value:
            name_input.placeholder = t("categories.name_placeholder")
        self.query_one("#lbl-cat-desc", Label).update(t("categories.description_label"))
        desc_input = self.query_one("#cat-desc", Input)
        if not desc_input.value:
            desc_input.placeholder = t("categories.description_placeholder")
        self.query_one("#lbl-cat-color", Label).update(t("categories.color_label"))
        self.query_one("#lbl-cat-parent", Label).update(t("categories.parent_label"))
        self.query_one("#cat-parent", Select).prompt = t("categories.parent_prompt")
        self.query_one("#btn-save-cat", Button).label = t("categories.save_button")
        self.query_one("#btn-cancel-cat", Button).label = t("categories.cancel_button")
        tab = self.app.query_one(TabbedContent).get_tab("tab-categories")
        tab.label = t("categories.tab_title")
        table = self.query_one("#cat-table", DataTable)
        table.clear(columns=True)
        self._setup_table()
        self._refresh()

    def _setup_table(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            t("categories.column_id"),
            t("categories.column_name"),
            t("categories.column_color"),
            t("categories.column_description"),
        )

    def on_mount(self) -> None:
        self._setup_table()
        self._refresh()

    def refresh_data(self) -> None:
        """Reload categories from DB. Called when this tab becomes active,
        since TabbedContent mounts all panes once at startup and on_mount() won't
        fire again on tab switch."""
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.clear()
        categories = db.get_categories()
        for c, depth in build_category_tree(categories):
            table.add_row(*category_row_cells(c, depth), key=str(c.id))
        self._selected_id = None
        self._toggle_edit_buttons(False)
        self._refresh_parent_picker(categories, editing_id=None)

    def _refresh_parent_picker(
        self, categories: list[Category], editing_id: Optional[int]
    ) -> None:
        select = self.query_one("#cat-parent", Select)
        select.set_options(parent_select_options(categories, editing_id))
        select.disabled = editing_id is not None and has_children(categories, editing_id)

    def _toggle_edit_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-edit-cat", Button).disabled = not enabled
        self.query_one("#btn-delete-cat", Button).disabled = not enabled

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "cat-table":
            self._selected_id = int(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-new-cat":
            self._clear_form()
            self._selected_id = None
        elif bid == "btn-edit-cat" and self._selected_id:
            categories = db.get_categories()
            cats = {c.id: c for c in categories}
            cat = cats.get(self._selected_id)
            if cat:
                self.query_one("#cat-name", Input).value = cat.name
                self.query_one("#cat-desc", Input).value = cat.description
                self.query_one("#cat-color", Input).value = cat.color
                self._refresh_parent_picker(categories, editing_id=self._selected_id)
                select = self.query_one("#cat-parent", Select)
                if cat.parent_id is not None:
                    select.value = cat.parent_id
                else:
                    select.clear()
        elif bid == "btn-delete-cat" and self._selected_id:
            db.delete_category(self._selected_id)
            forget_category_embedding(self._selected_id)
            self._refresh()
            self.query_one("#cat-feedback", Label).update(
                f"[green]{t('categories.deleted_feedback')}[/green]"
            )
        elif bid == "btn-save-cat":
            self._save()
        elif bid == "btn-cancel-cat":
            self._clear_form()

    def _save(self) -> None:
        name = self.query_one("#cat-name", Input).value.strip()
        desc = self.query_one("#cat-desc", Input).value.strip()
        color = self.query_one("#cat-color", Input).value.strip() or "#6366f1"
        fb = self.query_one("#cat-feedback", Label)
        if not name:
            fb.update(f"[red]{t('categories.name_required')}[/red]")
            return

        parent_select = self.query_one("#cat-parent", Select)
        parent_id = None if parent_select.is_blank() else int(parent_select.value)
        selected_id = self._selected_id
        is_edit = bool(selected_id)

        if is_edit:
            def save_fn() -> Category:
                db.update_category(selected_id, name, desc, color, parent_id)
                return Category(id=selected_id, name=name, description=desc, color=color, parent_id=parent_id)
        else:
            def save_fn() -> Category:
                return db.create_category(name, desc, color, parent_id)

        success, message, saved = save_category_feedback(is_edit, save_fn)
        fb.update(message)
        if not success:
            return
        sync_category_embedding(saved)
        self._refresh()
        self._clear_form()

    def _clear_form(self) -> None:
        self.query_one("#cat-name", Input).value = ""
        self.query_one("#cat-desc", Input).value = ""
        self.query_one("#cat-color", Input).value = "#6366f1"
        select = self.query_one("#cat-parent", Select)
        select.set_options(parent_select_options(db.get_categories(), editing_id=None))
        select.clear()
