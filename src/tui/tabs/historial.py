"""Tab 5: Historial — browse past call/video sessions and their fragments."""

from textual.app import ComposeResult
from textual.widgets import Button, DataTable, Label, TabbedContent, TabPane

import src.db.database as db
from src.i18n import t
from src.tui.screens.category_reclassify_modal import CategoryReclassifyModal
from src.tui.screens.fragment_edit_modal import FragmentEditModal


def _titled_sessions(sessions: list) -> list:
    """Filter out sessions with no title — untitled sessions are noise in Historial.

    Pure function — no side effects, easy to test without Textual.
    """
    return [s for s in sessions if s.title]


def _parse_session_row_key(key: str) -> tuple[str, int]:
    """Split a Historial session row key ("video:3" / "call:12") into (source, id).

    Pure function — no side effects, easy to test without Textual. A composite
    key is required because video_sessions.id and call_sessions.id are
    independent sequences and can collide.
    """
    source, _, session_id = key.partition(":")
    return source, int(session_id)


class HistorialTab(TabPane):
    """
    Browse past sessions (video AND call, unified) and their fragments.

    Layout:
      Top panel  — DataTable listing unified sessions (id, source, title, date).
      Bottom panel — DataTable listing fragments for the selected session
                     (#, excerpt, category label), pulled from unified_segments.
      "Reclasificar categoría..." opens CategoryReclassifyModal (global,
      across every session — moved out of this tab's body since it's an
      occasional action, not part of everyday browsing).
    """

    def __init__(self):
        super().__init__(t("historial.tab_title"), id="tab-historial")
        self._selected_source: str | None = None
        self._selected_session_id: int | None = None
        self._categories_cache: dict[int, str] = {}
        self._current_fragments: dict[str, db.UnifiedSegment] = {}

    def compose(self) -> ComposeResult:
        yield Label(t("historial.sessions_label"), id="lbl-historial-sessions")
        yield DataTable(id="historial-sessions-table")
        yield Label(t("historial.fragments_label"), id="lbl-historial-ideas")
        yield DataTable(id="historial-ideas-table")
        yield Button(t("historial.reclassify_button"), id="btn-open-reclassify", variant="default")
        yield Label("", id="historial-status")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and rebuild both DataTables'
        columns (clear+re-add, then repopulate — mirrors video.py's
        retranslate()). Sessions table repopulates unconditionally; the
        ideas table only if a session is currently selected (otherwise it
        stays empty with translated-but-empty headers, matching its normal
        pre-selection state). Doesn't touch the status line (result
        state)."""
        self.query_one("#lbl-historial-sessions", Label).update(t("historial.sessions_label"))
        self.query_one("#lbl-historial-ideas", Label).update(t("historial.fragments_label"))
        self.query_one("#btn-open-reclassify", Button).label = t("historial.reclassify_button")
        sessions_table = self.query_one("#historial-sessions-table", DataTable)
        sessions_table.clear(columns=True)
        ideas_table = self.query_one("#historial-ideas-table", DataTable)
        ideas_table.clear(columns=True)
        self._setup_tables()
        self._refresh_sessions()
        if self._selected_source is not None and self._selected_session_id is not None:
            self._load_ideas_for_session(self._selected_source, self._selected_session_id)
        tab = self.app.query_one(TabbedContent).get_tab("tab-historial")
        tab.label = t("historial.tab_title")

    def on_mount(self) -> None:
        self._setup_tables()
        self._load_categories()
        self._refresh_sessions()

    def refresh_data(self) -> None:
        """Reload sessions/categories from DB. Called when this tab becomes active,
        since TabbedContent mounts all panes once at startup and on_mount() won't
        fire again on tab switch."""
        self._load_categories()
        self._refresh_sessions()
        if self._selected_source is not None and self._selected_session_id is not None:
            self._load_ideas_for_session(self._selected_source, self._selected_session_id)

    def _load_categories(self) -> None:
        self._categories_cache = {c.id: c.name for c in db.get_categories()}

    def _setup_tables(self) -> None:
        sessions_table = self.query_one("#historial-sessions-table", DataTable)
        sessions_table.cursor_type = "row"
        sessions_table.add_columns(
            t("historial.column_id"), t("historial.column_source"),
            t("historial.column_title"), t("historial.column_date"),
        )

        ideas_table = self.query_one("#historial-ideas-table", DataTable)
        ideas_table.cursor_type = "row"
        ideas_table.add_columns(
            t("historial.column_number"), t("historial.column_fragment"),
            t("historial.column_category"),
        )

    def _refresh_sessions(self) -> None:
        table = self.query_one("#historial-sessions-table", DataTable)
        table.clear()
        sessions = _titled_sessions(db.get_unified_sessions())
        if not sessions:
            self.query_one("#historial-status", Label).update(
                f"[dim]{t('historial.no_sessions')}[/dim]"
            )
            return
        self.query_one("#historial-status", Label).update("")
        for s in sessions:
            source_label = t("historial.source_video") if s.source == "video" else t("historial.source_call")
            date_display = (s.created_at or "")[:16]
            table.add_row(
                str(s.id),
                source_label,
                s.title,
                date_display,
                key=f"{s.source}:{s.id}",
            )

    def _load_ideas_for_session(self, source: str, session_id: int) -> None:
        ideas_table = self.query_one("#historial-ideas-table", DataTable)
        ideas_table.clear()
        self._current_fragments = {}
        fragments = db.get_unified_segments(source=source, session_id=session_id)
        if not fragments:
            self.query_one("#historial-status", Label).update(
                f"[dim]{t('historial.no_fragments')}[/dim]"
            )
            return
        self.query_one("#historial-status", Label).update("")
        for i, frag in enumerate(fragments, start=1):
            excerpt = frag.text[:60] + ("…" if len(frag.text) > 60 else "")
            cat_label = (
                self._categories_cache.get(frag.category_id, "—")
                if frag.category_id
                else "—"
            )
            row_key = f"{frag.source}:{frag.id}"
            self._current_fragments[row_key] = frag
            ideas_table.add_row(str(i), excerpt, cat_label, key=row_key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "historial-sessions-table":
            source, session_id = _parse_session_row_key(event.row_key.value)
            self._selected_source = source
            self._selected_session_id = session_id
            self._load_ideas_for_session(source, session_id)
        elif event.data_table.id == "historial-ideas-table":
            frag = self._current_fragments.get(event.row_key.value)
            if frag is not None:
                self.app.push_screen(
                    FragmentEditModal(frag.source, frag.id, frag.text, frag.category_id),
                    self._on_fragment_edited,
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-open-reclassify":
            self.app.push_screen(CategoryReclassifyModal(), self._on_reclassify_closed)

    def _on_reclassify_closed(self, changed: bool | None) -> None:
        if changed:
            self.refresh_data()

    def _on_fragment_edited(self, changed: bool | None) -> None:
        if changed and self._selected_source is not None and self._selected_session_id is not None:
            self._load_ideas_for_session(self._selected_source, self._selected_session_id)
