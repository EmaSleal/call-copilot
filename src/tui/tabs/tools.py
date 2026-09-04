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


def _parse_tags_input(raw: str) -> list[str]:
    """Comma-separated tags Input value -> cleaned list, blanks dropped."""
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def format_add_tool_feedback(created: bool, name: str) -> str:
    """Feedback text for the 'Agregar tool' button."""
    key = "tools.add_success" if created else "tools.add_dedup_hit"
    return t(key, name=name)


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
        with Horizontal():
            yield Input(placeholder=t("tools.add_name_placeholder"), id="tools-add-name")
            yield Input(placeholder=t("tools.add_category_placeholder"), id="tools-add-category")
            yield Input(placeholder=t("tools.add_tags_placeholder"), id="tools-add-tags")
        with Horizontal():
            yield Input(placeholder=t("tools.add_description_placeholder"), id="tools-add-description")
            yield Input(placeholder=t("tools.add_url_placeholder"), id="tools-add-url")
            yield Button(t("tools.add_button"), id="btn-tools-add", variant="success")
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
        for input_id, key in (
            ("#tools-add-name", "tools.add_name_placeholder"),
            ("#tools-add-category", "tools.add_category_placeholder"),
            ("#tools-add-tags", "tools.add_tags_placeholder"),
            ("#tools-add-description", "tools.add_description_placeholder"),
            ("#tools-add-url", "tools.add_url_placeholder"),
        ):
            add_input = self.query_one(input_id, Input)
            if not add_input.value:
                add_input.placeholder = t(key)
        self.query_one("#btn-tools-add", Button).label = t("tools.add_button")
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

    def _add_tool(self) -> None:
        name = self.query_one("#tools-add-name", Input).value.strip()
        status = self.query_one("#tools-status", Label)
        if not name:
            status.update(f"[red]{t('tools.add_name_required')}[/red]")
            return

        category = self.query_one("#tools-add-category", Input).value.strip()
        description = self.query_one("#tools-add-description", Input).value.strip()
        tags = _parse_tags_input(self.query_one("#tools-add-tags", Input).value)
        source_url = self.query_one("#tools-add-url", Input).value.strip()

        from src.processing.tool_extractor import save_researched_tool
        tool, created = save_researched_tool(
            name, category=category, description=description,
            tags=tags, source_url=source_url,
        )

        for input_id in (
            "#tools-add-name", "#tools-add-category", "#tools-add-tags",
            "#tools-add-description", "#tools-add-url",
        ):
            self.query_one(input_id, Input).value = ""
        self._list_all()
        status.update(f"[green]{format_add_tool_feedback(created, tool.name)}[/green]")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-tools-search":
            query = self.query_one("#tools-query", Input).value.strip()
            if query:
                await self._run_search(query)
        elif event.button.id == "btn-tools-list-all":
            self._list_all()
        elif event.button.id == "btn-tools-add":
            self._add_tool()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tools-query":
            query = event.value.strip()
            if query:
                await self._run_search(query)
