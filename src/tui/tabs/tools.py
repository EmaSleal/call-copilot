"""Tab 6: Tools — catálogo de tecnologías detectadas en las llamadas."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, TabbedContent, TabPane

from src.db.database import Tool, get_tools
from src.i18n import t
from src.processing.tool_extractor import search_tools


def _tool_row(tool: Tool) -> tuple[str, str, str]:
    """Pure function — no side effects, easy to test without Textual."""
    category = tool.category or "—"
    detail = tool.summary or tool.description or ""
    if len(detail) > 80:
        detail = detail[:80] + "…"
    return (tool.name, category, detail)


class ToolsTab(TabPane):
    """
    Browse and search the tools catalog populated by post-call extraction
    (src/processing/tool_extractor.py). Search box on top (semantic, via
    search_tools()), full catalog listed by default and on refresh.
    """

    def __init__(self):
        super().__init__(t("tools.tab_title"), id="tab-tools")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder=t("tools.search_placeholder"), id="tools-query")
            yield Button(t("tools.search_button"), id="btn-tools-search", variant="primary")
            yield Button(t("tools.list_all_button"), id="btn-tools-list-all", variant="default")
        yield DataTable(id="tools-results")
        yield Label("", id="tools-status")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and rebuild the DataTable's
        columns (clear+re-add is the only way to relabel them, then
        repopulate — mirrors video.py's retranslate()). Doesn't touch the
        typed search query or the status line (result state)."""
        query_input = self.query_one("#tools-query", Input)
        if not query_input.value:
            query_input.placeholder = t("tools.search_placeholder")
        self.query_one("#btn-tools-search", Button).label = t("tools.search_button")
        self.query_one("#btn-tools-list-all", Button).label = t("tools.list_all_button")
        table = self.query_one("#tools-results", DataTable)
        table.clear(columns=True)
        table.add_columns(t("tools.column_name"), t("tools.column_category"), t("tools.column_summary"))
        self._list_all()
        tab = self.app.query_one(TabbedContent).get_tab("tab-tools")
        tab.label = t("tools.tab_title")

    def on_mount(self) -> None:
        table = self.query_one("#tools-results", DataTable)
        table.add_columns(t("tools.column_name"), t("tools.column_category"), t("tools.column_summary"))
        self.refresh_data()

    def refresh_data(self) -> None:
        """Called on initial mount AND when this tab becomes active again
        (see UnifiedApp.on_tabbed_content_tab_activated) — the catalog
        changes after every call, and TabbedContent panes mount once."""
        self._list_all()

    def _list_all(self) -> None:
        table = self.query_one("#tools-results", DataTable)
        table.clear()
        tools = get_tools()
        if not tools:
            self.query_one("#tools-status", Label).update(
                f"[dim]{t('tools.none_detected')}[/dim]"
            )
            return
        self.query_one("#tools-status", Label).update("")
        for tool in tools:
            table.add_row(*_tool_row(tool))

    async def _run_search(self, query: str) -> None:
        table = self.query_one("#tools-results", DataTable)
        table.clear()
        tools = await search_tools(query)
        if not tools:
            self.query_one("#tools-status", Label).update(
                f"[dim]{t('tools.no_results', query=query)}[/dim]"
            )
            return
        self.query_one("#tools-status", Label).update("")
        for tool in tools:
            table.add_row(*_tool_row(tool))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-tools-search":
            query = self.query_one("#tools-query", Input).value.strip()
            if query:
                await self._run_search(query)
        elif event.button.id == "btn-tools-list-all":
            self._list_all()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tools-query":
            query = event.value.strip()
            if query:
                await self._run_search(query)
