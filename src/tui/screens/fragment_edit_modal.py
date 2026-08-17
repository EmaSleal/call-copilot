"""
Modal: edit a single fragment's category. Launched from Historial's
fragments table — the bulk reclassify tool (CategoryReclassifyModal)
moves an entire category at once; this is the complement for fixing one
fragment at a time.
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static

import src.db.database as db
from src.i18n import t


def _update_fragment_category(source: str, fragment_id: int, category_id: int) -> None:
    """Dispatch to the right DAO based on source — segments.id and
    call_segments.id are independent sequences (video/call), so the
    source tag from the fragment's composite row key decides which
    table to write to."""
    if source == "video":
        db.update_segment_category(fragment_id, category_id)
    else:
        db.update_call_segment_category(fragment_id, category_id)


class FragmentEditModal(ModalScreen):
    """Shows the full fragment text and a category picker. Dismissed with
    True if the category was changed (caller should refresh), False/None
    otherwise."""

    CSS = """
    FragmentEditModal { align: center middle; }
    #fragment-dialog {
        width: 80; height: auto; max-height: 80%;
        background: #1e293b; border: solid #4f46e5;
        padding: 1 2;
    }
    #fragment-header { height: auto; align: left middle; margin-bottom: 1; }
    #fragment-title { text-style: bold; color: #f8fafc; width: 1fr; }
    #btn-fragment-close { width: auto; }
    #fragment-text { margin-bottom: 1; color: #cbd5e1; }
    #fragment-actions { height: auto; margin-top: 1; }
    #fragment-feedback { margin-top: 1; }
    """

    # Footer hint, same restart-required exception as UnifiedApp.BINDINGS
    # in src/tui/app.py — resolved once at import time.
    BINDINGS = [("escape", "close", t("fragment_edit.close_binding"))]

    def __init__(self, source: str, fragment_id: int, text: str, category_id: int | None) -> None:
        super().__init__()
        self._source = source
        self._fragment_id = fragment_id
        self._text = text
        self._category_id = category_id
        self._changed = False

    def action_close(self) -> None:
        self.dismiss(self._changed)

    def compose(self) -> ComposeResult:
        with Vertical(id="fragment-dialog"):
            with Horizontal(id="fragment-header"):
                yield Label(t("fragment_edit.title"), id="fragment-title")
                yield Button(t("fragment_edit.close_button"), id="btn-fragment-close", variant="default")
            yield Static(self._text, id="fragment-text")
            yield Label(t("fragment_edit.category_label"), id="lbl-fragment-category")
            yield Select([], id="fragment-category-select", allow_blank=True)
            with Horizontal(id="fragment-actions"):
                yield Button(t("fragment_edit.save_button"), id="btn-fragment-save", variant="primary")
            yield Label("", id="fragment-feedback")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome — not the fragment text (user
        data) or the feedback line (result state)."""
        self.query_one("#fragment-title", Label).update(t("fragment_edit.title"))
        self.query_one("#btn-fragment-close", Button).label = t("fragment_edit.close_button")
        self.query_one("#lbl-fragment-category", Label).update(t("fragment_edit.category_label"))
        self.query_one("#btn-fragment-save", Button).label = t("fragment_edit.save_button")

    def on_mount(self) -> None:
        select = self.query_one("#fragment-category-select", Select)
        options = [(c.name, c.id) for c in db.get_categories()]
        select.set_options(options)
        if self._category_id is not None:
            select.value = self._category_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-fragment-close":
            self.dismiss(self._changed)
        elif event.button.id == "btn-fragment-save":
            self._save()

    def _save(self) -> None:
        select = self.query_one("#fragment-category-select", Select)
        fb = self.query_one("#fragment-feedback", Label)
        if select.is_blank():
            fb.update(f"[yellow]{t('fragment_edit.pick_category')}[/yellow]")
            return
        new_category_id = int(select.value)
        if new_category_id == self._category_id:
            fb.update(f"[dim]{t('fragment_edit.no_changes')}[/dim]")
            return
        _update_fragment_category(self._source, self._fragment_id, new_category_id)
        self._category_id = new_category_id
        self._changed = True
        fb.update(f"[green]{t('fragment_edit.saved_feedback')}[/green]")
