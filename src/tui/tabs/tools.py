"""Tab 6: Tools — catálogo de tecnologías detectadas en las llamadas."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Label, TabPane

from src.db.database import Tool, get_tools
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
        super().__init__("🛠 Tools", id="tab-tools")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Buscar tecnología...", id="tools-query")
            yield Button("Buscar", id="btn-tools-search", variant="primary")
            yield Button("Ver todas", id="btn-tools-list-all", variant="default")
        yield DataTable(id="tools-results")
        yield Label("", id="tools-status")

    def on_mount(self) -> None:
        table = self.query_one("#tools-results", DataTable)
        table.add_columns("Nombre", "Categoría", "Resumen")
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
                "[dim]Todavía no se detectaron tecnologías.[/dim]"
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
                f"[dim]Sin resultados para «{query}».[/dim]"
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
