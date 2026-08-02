"""Tab 3: Búsqueda — search full-text en segmentos de BD."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, TabPane

import src.db.database as db


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


class SearchTab(TabPane):
    def __init__(self):
        super().__init__("🔍 Buscar", id="tab-search")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Buscar en transcripciones...", id="search-query")
            yield Button("Buscar", id="btn-search", variant="primary")
        yield DataTable(id="search-results")

    def on_mount(self) -> None:
        table = self.query_one("#search-results", DataTable)
        table.add_columns("Sesión", "Tiempo", "Categoría", "Fragmento")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search":
            query = self.query_one("#search-query", Input).value.strip()
            if query:
                self._run_search(query)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-query":
            self._run_search(event.value.strip())

    def _run_search(self, query: str) -> None:
        table = self.query_one("#search-results", DataTable)
        table.clear()
        results = db.search_segments(query)
        for r in results:
            start = _fmt_ts(r["start_s"])
            cat = r.get("cat_name") or "—"
            text = r["text"][:80] + ("…" if len(r["text"]) > 80 else "")
            title = (r.get("session_title") or "")[:30]
            table.add_row(title, start, cat, text)
