"""Tab 5: Historial — browse past call/video sessions and their fragments."""

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Label, Select, SelectionList, TabPane

import src.db.database as db
from src.tui.messages import CategoriesChanged
from src.tui.tabs.video import _partition_new_suggestions


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


async def _reclassify_category(category_id: int) -> int:
    """
    Re-check every segment (video AND call, across every session — not
    scoped to one) currently in category_id against the full, up-to-date
    category set (including categories just added), and move whichever
    ones now fit a different category better. Returns the number moved.

    Generalizes Video's _reclassify_otros: any category, not just
    "Otro"/"Otros", and global instead of session-scoped — a category like
    "Técnico" can span dozens of sessions, and breaking it down needs the
    LLM to see the whole pattern at once.

    Unlike _reclassify_otros, the target category is NOT excluded from the
    candidates offered to the classifier. Excluding "Otro" makes sense —
    it's a junk/fallback bucket, nothing should legitimately stay there.
    But this tool also runs on real, substantive categories: excluding the
    target forces every single fragment out with no "it still belongs
    here" option, scattering genuinely-fitting content into whatever
    unrelated category is the closest wrong match. (Confirmed against
    real data before this fix: 100% of a "Técnico" bucket got force-moved
    even though only a fraction actually matched the new sub-categories.)
    A fragment the classifier re-picks into category_id itself is left
    alone — that's not a move, so it isn't written or counted.
    """
    from src.video.classifier import classify_segments_batch

    categories = db.get_categories()

    video_segments = db.get_segments_by_category_global(category_id)
    call_segments = db.get_call_segments_by_category_global(category_id)

    loop = asyncio.get_running_loop()
    moved = 0

    if video_segments:
        texts = [s.text for s in video_segments]
        cat_ids = await loop.run_in_executor(None, lambda: classify_segments_batch(texts, categories))
        for seg, cat_id in zip(video_segments, cat_ids):
            if cat_id is not None and cat_id != category_id:
                db.update_segment_category(seg.id, cat_id)
                moved += 1

    if call_segments:
        texts = [s.text for s in call_segments]
        cat_ids = await loop.run_in_executor(None, lambda: classify_segments_batch(texts, categories))
        for seg, cat_id in zip(call_segments, cat_ids):
            if cat_id is not None and cat_id != category_id:
                db.update_call_segment_category(seg.id, cat_id)
                moved += 1

    return moved


class HistorialTab(TabPane):
    """
    Browse past sessions (video AND call, unified) and their fragments.

    Layout:
      Top panel  — DataTable listing unified sessions (id, source, title, date).
      Bottom panel — DataTable listing fragments for the selected session
                     (#, excerpt, category label), pulled from unified_segments.
    """

    def __init__(self):
        super().__init__("📋 Historial", id="tab-historial")
        self._selected_source: str | None = None
        self._selected_session_id: int | None = None
        self._categories_cache: dict[int, str] = {}
        self._reclassify_suggestions: list[dict] = []
        self._reclassify_target_category_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Label("Sesiones:")
        yield DataTable(id="historial-sessions-table")
        yield Label("Fragmentos:", id="lbl-historial-ideas")
        yield DataTable(id="historial-ideas-table")
        yield Label("Reclasificar categoría (global, todas las sesiones):")
        with Horizontal():
            yield Select([], id="reclassify-category-select", allow_blank=True)
            yield Button("Analizar", id="btn-reclassify-analyze", variant="primary")
        yield SelectionList(id="reclassify-suggestions")
        with Horizontal():
            yield Button(
                "Agregar seleccionadas", id="btn-reclassify-add",
                variant="success", disabled=True,
            )
        yield Label("", id="reclassify-feedback")
        yield Label("", id="historial-status")

    def on_mount(self) -> None:
        self._setup_tables()
        self._load_categories()
        self._refresh_sessions()
        self._refresh_category_select()

    def refresh_data(self) -> None:
        """Reload sessions/categories from DB. Called when this tab becomes active,
        since TabbedContent mounts all panes once at startup and on_mount() won't
        fire again on tab switch."""
        self._load_categories()
        self._refresh_sessions()
        self._refresh_category_select()
        if self._selected_source is not None and self._selected_session_id is not None:
            self._load_ideas_for_session(self._selected_source, self._selected_session_id)

    def _load_categories(self) -> None:
        self._categories_cache = {c.id: c.name for c in db.get_categories()}

    def _refresh_category_select(self) -> None:
        select = self.query_one("#reclassify-category-select", Select)
        options = [(c.name, c.id) for c in db.get_categories()]
        select.set_options(options)

    def _setup_tables(self) -> None:
        sessions_table = self.query_one("#historial-sessions-table", DataTable)
        sessions_table.cursor_type = "row"
        sessions_table.add_columns("ID", "Fuente", "Título", "Fecha")

        ideas_table = self.query_one("#historial-ideas-table", DataTable)
        ideas_table.cursor_type = "row"
        ideas_table.add_columns("#", "Fragmento", "Categoría")

    def _refresh_sessions(self) -> None:
        table = self.query_one("#historial-sessions-table", DataTable)
        table.clear()
        sessions = _titled_sessions(db.get_unified_sessions())
        if not sessions:
            self.query_one("#historial-status", Label).update(
                "[dim]No hay sesiones procesadas todavía.[/dim]"
            )
            return
        self.query_one("#historial-status", Label).update("")
        for s in sessions:
            source_label = "Video" if s.source == "video" else "Llamada"
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
        fragments = db.get_unified_segments(source=source, session_id=session_id)
        if not fragments:
            self.query_one("#historial-status", Label).update(
                "[dim]Esta sesión no tiene fragmentos procesados.[/dim]"
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
            ideas_table.add_row(str(i), excerpt, cat_label)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "historial-sessions-table":
            source, session_id = _parse_session_row_key(event.row_key.value)
            self._selected_source = source
            self._selected_session_id = session_id
            self._load_ideas_for_session(source, session_id)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-reclassify-analyze":
            select = self.query_one("#reclassify-category-select", Select)
            if not select.is_blank():
                await self._analyze_category(int(select.value))
            else:
                self.query_one("#reclassify-feedback", Label).update(
                    "[yellow]Elegí una categoría antes de analizar.[/yellow]"
                )
        elif event.button.id == "btn-reclassify-add":
            await self._add_selected_reclassify_suggestions()

    async def _analyze_category(self, category_id: int) -> None:
        from src.video.classifier import suggest_new_categories

        fb = self.query_one("#reclassify-feedback", Label)
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        btn_add = self.query_one("#btn-reclassify-add", Button)
        fb.update("Analizando...")

        try:
            categories = db.get_categories()
            video_segments = db.get_segments_by_category_global(category_id)
            call_segments = db.get_call_segments_by_category_global(category_id)
            all_texts = [s.text for s in video_segments] + [s.text for s in call_segments]

            if not all_texts:
                fb.update("[yellow]No hay fragmentos en esa categoría.[/yellow]")
                return

            loop = asyncio.get_running_loop()
            suggestions = await loop.run_in_executor(
                None, lambda: suggest_new_categories(all_texts, categories)
            )
            self._reclassify_suggestions = suggestions
            self._reclassify_target_category_id = category_id
            sel.clear_options()
            btn_add.disabled = True
            if suggestions:
                for i, s in enumerate(suggestions):
                    sel.add_option((f"{s['name']} — {s['description']}", i))
                btn_add.disabled = False
                fb.update(
                    f"[green]{len(suggestions)} sugerencia(s) de {len(all_texts)} fragmentos."
                    f" Marcá las que querés agregar.[/green]"
                )
            else:
                fb.update("[yellow]No se encontraron patrones recurrentes.[/yellow]")
        except Exception as e:
            fb.update(f"[red]Error al analizar: {e}[/red]")

    async def _add_selected_reclassify_suggestions(self) -> None:
        sel = self.query_one("#reclassify-suggestions", SelectionList)
        fb = self.query_one("#reclassify-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update("[yellow]Marcá al menos una sugerencia antes de agregar.[/yellow]")
            return

        existing_names = {c.name for c in db.get_categories()}
        selected = [
            self._reclassify_suggestions[i]
            for i in selected_indices if i < len(self._reclassify_suggestions)
        ]
        new_ones, duplicates = _partition_new_suggestions(selected, existing_names)

        for s in new_ones:
            db.create_category(s["name"], s["description"])

        remaining = [
            s for i, s in enumerate(self._reclassify_suggestions) if i not in set(selected_indices)
        ]
        self._reclassify_suggestions = remaining
        sel.clear_options()
        for i, s in enumerate(remaining):
            sel.add_option((f"{s['name']} — {s['description']}", i))
        if not remaining:
            self.query_one("#btn-reclassify-add", Button).disabled = True

        parts = []
        if new_ones:
            parts.append(f"Agregadas: {', '.join(s['name'] for s in new_ones)}.")
        if duplicates:
            parts.append(f"Ya existían (omitidas): {', '.join(s['name'] for s in duplicates)}.")
        self.post_message(CategoriesChanged())
        self._refresh_category_select()

        target_cat_id = self._reclassify_target_category_id
        if target_cat_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] Reclasificando...")
        moved = await _reclassify_category(target_cat_id)
        fb.update(f"[green]{' '.join(parts)} {moved} fragmento(s) reclasificado(s).[/green]")

        self._refresh_sessions()
        if self._selected_source is not None and self._selected_session_id is not None:
            self._load_ideas_for_session(self._selected_source, self._selected_session_id)
