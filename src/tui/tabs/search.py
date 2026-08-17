"""Tab 3: Búsqueda — full-text SQL en segmentos de BD, más búsqueda
semántica opcional (video + llamadas) cuando hay OPENAI_API_KEY."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, TabbedContent, TabPane

import src.db.database as db
from src.i18n import t
from src.processing.search_indexer import search_segments_semantic


def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _semantic_result_row(result: dict) -> tuple[str, str, str, str]:
    """Pure function — no side effects, easy to test without Textual."""
    if result["source"] == "video":
        origin = t("search.source_video")
        tiempo = _fmt_ts(result.get("start_s", 0.0))
    else:
        origin = t("search.source_call")
        tiempo = "—"
    text = result["text"]
    text = text[:80] + ("…" if len(text) > 80 else "")
    return (origin, tiempo, "—", text)


class SearchTab(TabPane):
    def __init__(self):
        super().__init__(t("search.tab_title"), id="tab-search")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder=t("search.query_placeholder"), id="search-query")
            yield Button(t("search.search_button"), id="btn-search", variant="primary")
            yield Button(t("search.semantic_button"), id="btn-search-semantic", variant="default")
        yield DataTable(id="search-results")
        yield Label("", id="search-status")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and rebuild the DataTable's
        columns (clear+re-add — results themselves are query-driven, left
        empty since there's no cached last-query state to replay)."""
        query_input = self.query_one("#search-query", Input)
        if not query_input.value:
            query_input.placeholder = t("search.query_placeholder")
        self.query_one("#btn-search", Button).label = t("search.search_button")
        self.query_one("#btn-search-semantic", Button).label = t("search.semantic_button")
        table = self.query_one("#search-results", DataTable)
        table.clear(columns=True)
        table.add_columns(
            t("search.column_session"), t("search.column_time"),
            t("search.column_category"), t("search.column_fragment"),
        )
        tab = self.app.query_one(TabbedContent).get_tab("tab-search")
        tab.label = t("search.tab_title")

    def on_mount(self) -> None:
        table = self.query_one("#search-results", DataTable)
        table.add_columns(
            t("search.column_session"), t("search.column_time"),
            t("search.column_category"), t("search.column_fragment"),
        )

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
        status.update("" if results else f"[dim]{t('search.no_results')}[/dim]")
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
            status.update(f"[dim]{t('search.no_results_semantic')}[/dim]")
            return
        status.update("")
        for r in results:
            table.add_row(*_semantic_result_row(r))
