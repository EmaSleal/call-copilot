"""Tab 4: Categorías — CRUD de taxonomía."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, TabPane

import src.db.database as db


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
        for c in db.get_categories():
            table.add_row(str(c.id), c.name, c.color, c.description[:40], key=str(c.id))
        self._selected_id = None
        self._toggle_edit_buttons(False)

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
            cats = {c.id: c for c in db.get_categories()}
            cat = cats.get(self._selected_id)
            if cat:
                self.query_one("#cat-name", Input).value = cat.name
                self.query_one("#cat-desc", Input).value = cat.description
                self.query_one("#cat-color", Input).value = cat.color
        elif bid == "btn-delete-cat" and self._selected_id:
            db.delete_category(self._selected_id)
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
        if self._selected_id:
            db.update_category(self._selected_id, name, desc, color)
            fb.update("[green]Categoría actualizada.[/green]")
        else:
            db.create_category(name, desc, color)
            fb.update("[green]Categoría creada.[/green]")
        self._refresh()
        self._clear_form()

    def _clear_form(self) -> None:
        self.query_one("#cat-name", Input).value = ""
        self.query_one("#cat-desc", Input).value = ""
        self.query_one("#cat-color", Input).value = "#6366f1"
