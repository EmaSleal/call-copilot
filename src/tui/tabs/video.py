"""Tab 2: Video Transcriber — procesar URL de YouTube, historial de sesiones."""

import asyncio
import shutil

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ProgressBar,
    SelectionList,
    TabbedContent,
    TabPane,
)

import src.db.database as db
from src.core import config_defaults
from src.i18n import t
from src.processing.category_dedup import (
    DedupVerdict,
    create_checked_suggestions,
    dedup_suggestions,
    verdict_label,
)
from src.processing.category_reclassify import find_otro_category, reclassify_otros
from src.tui.messages import CategoriesChanged
from src.tui.screens.session_modal import SessionModal


class VideoTab(TabPane):
    def __init__(self):
        super().__init__(t("video.tab_title"), id="tab-video")
        self._selected_session_id: int | None = None
        self._suggestions: list[dict] = []
        self._verdicts: list[DedupVerdict] = []
        self._sessions_cache: dict[int, tuple] = {}

    def compose(self) -> ComposeResult:
        yield Label(t("video.url_label"), id="lbl-video-url")
        with Horizontal():
            yield Input(placeholder="https://youtube.com/watch?v=...", id="video-url")
            yield Button(t("video.process_button"), id="btn-process-video", variant="primary")
        yield ProgressBar(id="video-progress", total=100, show_eta=False)
        yield Label("", id="video-status")
        yield Label(t("video.sessions_label"), id="lbl-sessions")
        yield DataTable(id="sessions-table")
        yield Label(t("video.suggestions_label"), id="lbl-suggestions")
        yield SelectionList(id="suggestions-list")
        with Horizontal():
            yield Button(
                t("video.add_selected_button"),
                id="btn-add-suggestion",
                variant="success",
                disabled=True,
            )
        yield Label("", id="suggestion-feedback")

    def retranslate(self) -> None:
        """Re-apply t() to static chrome and DataTable column headers (the
        table has to be cleared+rebuilt to relabel columns — no lighter API
        for that in this Textual version — then repopulated from DB, same
        as refresh_data()/on_mount()). Doesn't touch session row data
        (DB content) or the feedback/suggestions lines (result state)."""
        self.query_one("#lbl-video-url", Label).update(t("video.url_label"))
        self.query_one("#btn-process-video", Button).label = t("video.process_button")
        self.query_one("#lbl-sessions", Label).update(t("video.sessions_label"))
        self.query_one("#lbl-suggestions", Label).update(t("video.suggestions_label"))
        self.query_one("#btn-add-suggestion", Button).label = t("video.add_selected_button")
        table = self.query_one("#sessions-table", DataTable)
        table.clear(columns=True)
        self._setup_table()
        self._refresh_sessions()
        tab = self.app.query_one(TabbedContent).get_tab("tab-video")
        tab.label = t("video.tab_title")

    def on_mount(self) -> None:
        self._setup_table()
        self._refresh_sessions()

    def _setup_table(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            t("video.column_id"),
            t("video.column_title"),
            t("video.column_status"),
            t("video.column_date"),
            t("video.column_segments"),
        )

    def _refresh_sessions(self) -> None:
        self._sessions_cache = {}
        table = self.query_one("#sessions-table", DataTable)
        table.clear()
        for s in db.get_video_sessions():
            n_segs = len(db.get_segments(s.id)) if s.id else 0
            self._sessions_cache[s.id] = (s, n_segs)
            table.add_row(
                str(s.id),
                s.title[:50],
                s.status,
                s.created_at[:16],
                str(n_segs),
                key=str(s.id),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "sessions-table":
            session_id = int(event.row_key.value)
            self._selected_session_id = session_id
            self._selected_suggestion_idx = None
            session, n_segs = self._sessions_cache.get(session_id, (None, 0))
            if session:
                self.app.push_screen(
                    SessionModal(
                        session.title,
                        session.status,
                        session.url,
                        session.created_at[:16],
                        n_segs,
                    ),
                    self._on_modal_action,
                )

    def _on_modal_action(self, action: str | None) -> None:
        sid = self._selected_session_id
        if sid is None or action is None:
            return
        if action == "analyze":
            asyncio.create_task(self._analyze_others(sid))
        elif action == "delete":
            from src.processing.search_indexer import forget_segment_embeddings
            from src.video.pipeline import OUTPUT_DIR

            segment_ids = [s.id for s in db.get_segments(sid)]
            db.delete_video_session(sid)
            forget_segment_embeddings("video", segment_ids)
            session_dir = OUTPUT_DIR / str(sid)
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
            self._selected_session_id = None
            self._refresh_sessions()
        elif action == "reprocess":
            session, _ = self._sessions_cache.get(sid, (None, 0))
            if session:
                asyncio.create_task(self._process_video(session.url))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-process-video":
            url = self.query_one("#video-url", Input).value.strip()
            if url:
                asyncio.create_task(self._process_video(url))
        elif event.button.id == "btn-add-suggestion":
            asyncio.create_task(self._add_selected_suggestions())

    async def _process_video(self, url: str) -> None:
        from src.video.pipeline import run_pipeline

        progress_bar = self.query_one("#video-progress", ProgressBar)
        status_lbl = self.query_one("#video-status", Label)
        btn = self.query_one("#btn-process-video", Button)
        btn.disabled = True
        btn.label = t("video.processing_button")

        def on_progress(msg: str, pct: float):
            # callback desde el thread del executor — actualizamos via call_from_thread
            self.app.call_from_thread(progress_bar.update, progress=int(pct * 100))
            self.app.call_from_thread(status_lbl.update, msg)

        try:
            loop = asyncio.get_running_loop()
            model_size = config_defaults.whisper_model_video()
            await loop.run_in_executor(
                None, lambda: run_pipeline(url, model_size, on_progress)
            )
            status_lbl.update(f"[green]{t('video.processed_ok')}[/green]")
        except Exception as e:
            status_lbl.update(f"[red]{t('video.process_error', error=e)}[/red]")
        finally:
            btn.disabled = False
            btn.label = t("video.process_button")
            self._refresh_sessions()

    async def _analyze_others(self, session_id: int) -> None:
        from src.video.classifier import suggest_new_categories

        fb = self.query_one("#suggestion-feedback", Label)
        sel = self.query_one("#suggestions-list", SelectionList)
        btn_add = self.query_one("#btn-add-suggestion", Button)
        fb.update(t("video.analyzing_otros"))

        try:
            categories = db.get_categories()
            otros = find_otro_category(categories)
            segments = db.get_segments_by_category(
                session_id, otros.id if otros else None
            )

            if not segments:
                fb.update(f"[yellow]{t('video.no_otros_segments')}[/yellow]")
                return

            loop = asyncio.get_running_loop()
            texts = [s.text for s in segments]

            def _suggest_and_dedup():
                suggestions = suggest_new_categories(texts, categories)
                return dedup_suggestions(suggestions, categories)

            verdicts = await loop.run_in_executor(None, _suggest_and_dedup)
            self._verdicts = verdicts
            self._suggestions = [v.suggestion for v in verdicts]
            sel.clear_options()
            btn_add.disabled = True
            if verdicts:
                for i, v in enumerate(verdicts):
                    sel.add_option((verdict_label(v), i))
                btn_add.disabled = False
                fb.update(
                    f"[green]{t('video.suggestions_found', count=len(verdicts))}[/green]"
                )
            else:
                fb.update(f"[yellow]{t('video.no_patterns_found')}[/yellow]")
        except Exception as e:
            fb.update(f"[red]{t('video.analyze_error', error=e)}[/red]")

    async def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#suggestions-list", SelectionList)
        fb = self.query_one("#suggestion-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update(
                f"[yellow]{t('video.pick_suggestion_first')}[/yellow]"
            )
            return

        added, forced, skipped = await create_checked_suggestions(
            selected_indices, self._verdicts
        )

        remaining = [
            v for i, v in enumerate(self._verdicts) if i not in set(selected_indices)
        ]
        self._verdicts = remaining
        self._suggestions = [v.suggestion for v in remaining]
        sel.clear_options()
        for i, v in enumerate(remaining):
            sel.add_option((verdict_label(v), i))
        if not remaining:
            self.query_one("#btn-add-suggestion", Button).disabled = True

        parts = []
        if added:
            parts.append(t("video.added_summary", names=", ".join(added)))
        if forced:
            parts.append(t("video.forced_summary", names=", ".join(forced)))
        if skipped:
            parts.append(t("video.skipped_summary", names=", ".join(skipped)))
        self.post_message(CategoriesChanged())

        session_id = self._selected_session_id
        if session_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] {t('video.reclassifying_otros_suffix')}")
        moved = await reclassify_otros(session_id)
        fb.update(
            f"[green]{' '.join(parts)} "
            f"{t('video.reclassified_otros_summary', count=moved)}[/green]"
        )
