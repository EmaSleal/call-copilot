"""Tab 7: Pendientes — revisar y aprobar/rechazar deletes propuestos por el
agente de mantenimiento del catálogo (src.agent.maintenance). D2: el
agente escribe de forma autónoma, pero un delete siempre espera a un
humano — esta tab es ese punto de aprobación."""

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label, TabbedContent, TabPane

import src.db.database as db
from src.agent import catalog_commands
from src.agent.commands import approve_pending_action, reject_pending_action
from src.db.database import PendingAction
from src.i18n import t


def format_pending_row(pa: PendingAction) -> tuple[str, str, str, str, str]:
    """Display row for a pending action. Pure function — no side effects,
    easy to test without Textual. Mirrors format_category_row's precedent
    in src/tui/tabs/categories.py."""
    return (
        str(pa.id),
        pa.action,
        f"{pa.table_name}:{pa.row_id}",
        pa.reason or "—",
        pa.created_at[:16],
    )


class PendingActionsTab(TabPane):
    def __init__(self):
        super().__init__(t("pending_actions.tab_title"), id="tab-pending")
        self._selected_id: Optional[int] = None

    def compose(self) -> ComposeResult:
        yield Label(t("pending_actions.description_label"), id="lbl-pending-description")
        yield DataTable(id="pending-table")
        with Horizontal():
            yield Button(
                t("pending_actions.approve_button"), id="btn-approve-pending",
                variant="success", disabled=True,
            )
            yield Button(
                t("pending_actions.reject_button"), id="btn-reject-pending",
                variant="error", disabled=True,
            )
        yield Label("", id="pending-feedback")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and rebuild the DataTable's
        columns (clear+re-add, then repopulate — mirrors video.py's
        retranslate()). Doesn't touch the feedback line (result state)."""
        self.query_one("#lbl-pending-description", Label).update(
            t("pending_actions.description_label")
        )
        self.query_one("#btn-approve-pending", Button).label = t("pending_actions.approve_button")
        self.query_one("#btn-reject-pending", Button).label = t("pending_actions.reject_button")
        table = self.query_one("#pending-table", DataTable)
        table.clear(columns=True)
        self._setup_table()
        self._refresh()
        tab = self.app.query_one(TabbedContent).get_tab("tab-pending")
        tab.label = t("pending_actions.tab_title")

    def _setup_table(self) -> None:
        table = self.query_one("#pending-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            t("pending_actions.column_id"),
            t("pending_actions.column_action"),
            t("pending_actions.column_target"),
            t("pending_actions.column_reason"),
            t("pending_actions.column_date"),
        )

    def on_mount(self) -> None:
        self._setup_table()
        catalog_commands.register_all()
        self._refresh()

    def refresh_data(self) -> None:
        """Reload pending actions. Called when this tab becomes active,
        since TabbedContent mounts all panes once at startup and on_mount()
        won't fire again on tab switch."""
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#pending-table", DataTable)
        table.clear()
        for pa in db.get_pending_actions():
            table.add_row(*format_pending_row(pa), key=str(pa.id))
        self._selected_id = None
        self._toggle_buttons(False)

    def _toggle_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-approve-pending", Button).disabled = not enabled
        self.query_one("#btn-reject-pending", Button).disabled = not enabled

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "pending-table":
            self._selected_id = int(event.row_key.value)
            self._toggle_buttons(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        fb = self.query_one("#pending-feedback", Label)
        if bid == "btn-approve-pending" and self._selected_id:
            try:
                approve_pending_action(self._selected_id, resolved_by="human")
            except Exception as e:
                fb.update(f"[red]{t('pending_actions.approve_error', error=e)}[/red]")
                return
            self._refresh()
            fb.update(f"[green]{t('pending_actions.approved_feedback')}[/green]")
        elif bid == "btn-reject-pending" and self._selected_id:
            reject_pending_action(self._selected_id, resolved_by="human")
            self._refresh()
            fb.update(f"[yellow]{t('pending_actions.rejected_feedback')}[/yellow]")
