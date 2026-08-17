"""Modal: detalle de sesión de video. Launched from VideoTab's sessions table."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from src.i18n import t


class SessionModal(ModalScreen):
    CSS = """
    SessionModal { align: center middle; }
    #modal-dialog {
        width: 72; height: auto;
        background: #1e293b; border: solid #4f46e5;
        padding: 2 3;
    }
    #modal-title  { text-style: bold; color: #f8fafc; margin-bottom: 1; }
    #modal-status { margin-bottom: 0; }
    #modal-meta   { color: #64748b; margin-bottom: 2; }
    #modal-actions { height: auto; margin-top: 1; }
    """

    def __init__(self, title: str, status: str, url: str, date: str, n_segs: int):
        super().__init__()
        self._title = title
        self._status = status
        self._url = url
        self._date = date
        self._n_segs = n_segs

    def compose(self) -> ComposeResult:
        status_color = {"done": "green", "error": "red", "processing": "yellow"}.get(
            self._status, "white"
        )
        with Vertical(id="modal-dialog"):
            yield Label(self._title[:65], id="modal-title")
            yield Label(
                f"[{status_color}]{self._status}[/{status_color}]  •  "
                f"{t('session_modal.segments_count', count=self._n_segs)}  •  {self._date}",
                id="modal-status",
            )
            yield Label(self._url[:65], id="modal-meta")
            with Horizontal(id="modal-actions"):
                yield Button(
                    t("session_modal.analyze_button"), id="btn-modal-analyze", variant="warning"
                )
                yield Button(t("session_modal.reprocess_button"), id="btn-modal-reprocess", variant="primary")
                yield Button(t("session_modal.delete_button"), id="btn-modal-delete", variant="error")
                yield Button(t("session_modal.close_button"), id="btn-modal-close", variant="default")

    def retranslate(self) -> None:
        """Re-apply t() to button labels and the status line's translatable
        segment-count phrase — status/date/n_segs stay sourced from the
        stored instance attrs, title/url (user data) untouched."""
        status_color = {"done": "green", "error": "red", "processing": "yellow"}.get(
            self._status, "white"
        )
        self.query_one("#modal-status", Label).update(
            f"[{status_color}]{self._status}[/{status_color}]  •  "
            f"{t('session_modal.segments_count', count=self._n_segs)}  •  {self._date}"
        )
        self.query_one("#btn-modal-analyze", Button).label = t("session_modal.analyze_button")
        self.query_one("#btn-modal-reprocess", Button).label = t("session_modal.reprocess_button")
        self.query_one("#btn-modal-delete", Button).label = t("session_modal.delete_button")
        self.query_one("#btn-modal-close", Button).label = t("session_modal.close_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-close":
            self.dismiss(None)
        elif event.button.id == "btn-modal-analyze":
            self.dismiss("analyze")
        elif event.button.id == "btn-modal-reprocess":
            self.dismiss("reprocess")
        elif event.button.id == "btn-modal-delete":
            self.dismiss("delete")
