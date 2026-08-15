"""Tab 4: Categorías — CRUD de taxonomía."""

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, TabPane

import src.db.database as db
from src.db.database import Category
from src.processing.category_dedup import forget_category_embedding, sync_category_embedding


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
        "[green]Categoría actualizada.[/green]"
        if is_edit
        else "[green]Categoría creada.[/green]"
    )
    return True, message, saved


class CategoriesTab(TabPane):
    def __init__(self):
        super().__init__("🏷  Categorías", id="tab-categories")
        self._selected_id = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="cat-layout"):
            with Vertical(id="cat-list-panel"):
                yield Label("Categorías existentes")
                yield DataTable(id="cat-table")
                with Horizontal():
                    yield Button("+ Nueva", id="btn-new-cat", variant="success")
                    yield Button(
                        "Editar", id="btn-edit-cat", variant="default", disabled=True
                    )
                    yield Button(
                        "Borrar", id="btn-delete-cat", variant="error", disabled=True
                    )
            with Vertical(id="cat-form-panel"):
                yield Label("Nombre:")
                yield Input(id="cat-name", placeholder="Ej: Marketing")
                yield Label("Descripción:")
                yield Input(id="cat-desc", placeholder="Descripción breve")
                yield Label("Color (hex):")
                yield Input(id="cat-color", placeholder="#6366f1", value="#6366f1")
                yield Label("Categoría padre:")
                yield Select(
                    [],
                    id="cat-parent",
                    allow_blank=True,
                    prompt="— Sin padre (nivel superior) —",
                )
                with Horizontal():
                    yield Button("Guardar", id="btn-save-cat", variant="primary")
                    yield Button("Cancelar", id="btn-cancel-cat", variant="default")
                yield Label("", id="cat-feedback")

    def on_mount(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Nombre", "Color", "Descripción")
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
            table.add_row(
                str(c.id), format_category_row(c, depth), c.color, c.description[:40], key=str(c.id)
            )
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
                select.value = cat.parent_id if cat.parent_id is not None else Select.BLANK
        elif bid == "btn-delete-cat" and self._selected_id:
            db.delete_category(self._selected_id)
            forget_category_embedding(self._selected_id)
            self._refresh()
            self.query_one("#cat-feedback", Label).update(
                "[green]Categoría eliminada.[/green]"
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
            fb.update("[red]El nombre no puede estar vacío.[/red]")
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
        select.value = Select.BLANK
