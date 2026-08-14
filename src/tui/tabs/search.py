"""Tab 3: Búsqueda — full-text SQL en segmentos de BD, más búsqueda
semántica opcional (video + llamadas) cuando hay OPENAI_API_KEY."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, TabPane

import src.db.database as db
from src.processing.search_indexer import search_segments_semantic


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _semantic_result_row(result: dict) -> tuple[str, str, str, str]:
    """Pure function — no side effects, easy to test without Textual."""
    if result["source"] == "video":
        origin = "Video"
        tiempo = _fmt_ts(result.get("start_s", 0.0))
    else:
        origin = "Llamada"
        tiempo = "—"
    text = result["text"]
    text = text[:80] + ("…" if len(text) > 80 else "")
    return (origin, tiempo, "—", text)


class SearchTab(TabPane):
    def __init__(self):
        super().__init__("🔍 Buscar", id="tab-search")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Buscar en transcripciones...", id="search-query")
            yield Button("Buscar", id="btn-search", variant="primary")
            yield Button("Buscar (semántico)", id="btn-search-semantic", variant="default")
        yield DataTable(id="search-results")
        yield Label("", id="search-status")

    def on_mount(self) -> None:
        table = self.query_one("#search-results", DataTable)
        table.add_columns("Sesión", "Tiempo", "Categoría", "Fragmento")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        query = self.query_one("#search-query", Input).value.strip()
        if not query:
            return
        if event.button.id == "btn-search":
            self._run_search(query)
        elif event.button.id == "btn-search-semantic":
            await self._run_semantic_search(query)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-query":
            self._run_search(event.value.strip())

    def _run_search(self, query: str) -> None:
        table = self.query_one("#search-results", DataTable)
        table.clear()
        results = db.search_segments(query)
        status = self.query_one("#search-status", Label)
        status.update("" if results else "[dim]Sin resultados.[/dim]")
        for r in results:
            start = _fmt_ts(r["start_s"])
            cat = r.get("cat_name") or "—"
            text = r["text"][:80] + ("…" if len(r["text"]) > 80 else "")
            title = (r.get("session_title") or "")[:30]
            table.add_row(title, start, cat, text)

    async def _run_semantic_search(self, query: str) -> None:
        table = self.query_one("#search-results", DataTable)
        table.clear()
        results = await search_segments_semantic(query)
        status = self.query_one("#search-status", Label)
        if not results:
            status.update("[dim]Sin resultados (¿OPENAI_API_KEY configurada?).[/dim]")
            return
        status.update("")
        for r in results:
            table.add_row(*_semantic_result_row(r))
