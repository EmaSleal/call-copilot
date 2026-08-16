"""Tab 2: Video Transcriber — procesar URL de YouTube, historial de sesiones."""

import asyncio
import shutil
import sqlite3

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ProgressBar,
    SelectionList,
    TabPane,
)

import src.db.database as db
from src.core import config_defaults
from src.processing.category_dedup import DedupVerdict, dedup_suggestions, sync_category_embedding
from src.tui.messages import CategoriesChanged
from src.tui.screens.session_modal import SessionModal


def _find_otro_category(categories: list):
    """Locate the fallback 'Otro'/'Otros' category by name, case-insensitive.

    Pure function — no side effects, easy to test without Textual.
    """
    return next((c for c in categories if c.name.lower() in ("otro", "otros")), None)


def _verdict_label(verdict: DedupVerdict) -> str:
    """Option label for the suggestions `SelectionList`: a genuinely new
    suggestion shows its name/description; a suggestion `dedup_suggestions()`
    matched to an existing category is prefixed with "≈" and shows what it
    already duplicates, with the cosine distance appended on the embeddings
    path (spec: Duplicate shown with override).

    Pure function — no side effects, easy to test without Textual.
    """
    s = verdict.suggestion
    if verdict.match is None:
        return f"{s['name']} — {s['description']}"
    label = f"≈ {s['name']} — Ya existe: {verdict.match.name}"
    if verdict.backend == "embeddings" and verdict.distance is not None:
        label += f" (d={verdict.distance:.2f})"
    return label


async def _create_checked_suggestions(
    selected_indices, verdicts: list[DedupVerdict]
) -> tuple[list[str], list[str], list[str]]:
    """Create every checked suggestion, regardless of its dedup verdict —
    checking a suggestion labelled as a duplicate IS the force-create
    override (spec: User overrides). `db.create_category` is UNIQUE-name
    safe: an actual collision at write time is reported as skipped instead
    of crashing the TUI (spec: Duplicates surfaced, never silently
    dropped). Returns `(added, forced, skipped)` category names.
    """
    added, forced, skipped = [], [], []
    for i in selected_indices:
        if i >= len(verdicts):
            continue
        verdict = verdicts[i]
        s = verdict.suggestion
        try:
            created = db.create_category(s["name"], s["description"])
        except sqlite3.IntegrityError:
            skipped.append(s["name"])
            continue
        (forced if verdict.match is not None else added).append(s["name"])
        sync_category_embedding(created)
    return added, forced, skipped


async def _reclassify_otros(session_id: int) -> int:
    """
    Re-check current 'Otro' segments of a session against the full, up-to-date
    category set (including categories just added) — without reprocessing the
    whole video. Returns the number of segments moved.
    """
    from src.video.classifier import classify_segments_batch

    categories = db.get_categories()
    otros = _find_otro_category(categories)
    if otros is None:
        return 0

    segments = db.get_segments_by_category(session_id, otros.id)
    if not segments:
        return 0

    candidates = [c for c in categories if c.id != otros.id]
    texts = [s.text for s in segments]
    loop = asyncio.get_running_loop()
    cat_ids = await loop.run_in_executor(
        None, lambda: classify_segments_batch(texts, candidates)
    )

    moved = 0
    for seg, cat_id in zip(segments, cat_ids):
        if cat_id is not None:
            db.update_segment_category(seg.id, cat_id)
            moved += 1
    return moved


class VideoTab(TabPane):
    def __init__(self):
        super().__init__("🎬 Video", id="tab-video")
        self._selected_session_id: int | None = None
        self._suggestions: list[dict] = []
        self._verdicts: list[DedupVerdict] = []
        self._sessions_cache: dict[int, tuple] = {}

    def compose(self) -> ComposeResult:
        yield Label("URL de YouTube o archivo local:")
        with Horizontal():
            yield Input(placeholder="https://youtube.com/watch?v=...", id="video-url")
            yield Button("▶ Procesar", id="btn-process-video", variant="primary")
        yield ProgressBar(id="video-progress", total=100, show_eta=False)
        yield Label("", id="video-status")
        yield Label("Sesiones procesadas (Enter para ver opciones):", id="lbl-sessions")
        yield DataTable(id="sessions-table")
        yield Label("Sugerencias de categorías:", id="lbl-suggestions")
        yield SelectionList(id="suggestions-list")
        with Horizontal():
            yield Button(
                "Agregar seleccionadas",
                id="btn-add-suggestion",
                variant="success",
                disabled=True,
            )
        yield Label("", id="suggestion-feedback")

    def on_mount(self) -> None:
        self._setup_table()
        self._refresh_sessions()

    def _setup_table(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Título", "Estado", "Fecha", "Segmentos")

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
        btn.label = "⏳ Procesando..."

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
            status_lbl.update("[green]✓ Procesado correctamente[/green]")
        except Exception as e:
            status_lbl.update(f"[red]Error: {e}[/red]")
        finally:
            btn.disabled = False
            btn.label = "▶ Procesar"
            self._refresh_sessions()

    async def _analyze_others(self, session_id: int) -> None:
        from src.video.classifier import suggest_new_categories

        fb = self.query_one("#suggestion-feedback", Label)
        sel = self.query_one("#suggestions-list", SelectionList)
        btn_add = self.query_one("#btn-add-suggestion", Button)
        fb.update("Analizando segmentos 'Otros'...")

        try:
            categories = db.get_categories()
            otros = _find_otro_category(categories)
            segments = db.get_segments_by_category(
                session_id, otros.id if otros else None
            )

            if not segments:
                fb.update("[yellow]No hay segmentos 'Otros' en esta sesión.[/yellow]")
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
                    sel.add_option((_verdict_label(v), i))
                btn_add.disabled = False
                fb.update(
                    f"[green]{len(verdicts)} sugerencia(s). Marcá las que querés agregar.[/green]"
                )
            else:
                fb.update("[yellow]No se encontraron patrones recurrentes.[/yellow]")
        except Exception as e:
            fb.update(f"[red]Error al analizar: {e}[/red]")

    async def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#suggestions-list", SelectionList)
        fb = self.query_one("#suggestion-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update(
                "[yellow]Marcá al menos una sugerencia antes de agregar.[/yellow]"
            )
            return

        added, forced, skipped = await _create_checked_suggestions(
            selected_indices, self._verdicts
        )

        remaining = [
            v for i, v in enumerate(self._verdicts) if i not in set(selected_indices)
        ]
        self._verdicts = remaining
        self._suggestions = [v.suggestion for v in remaining]
        sel.clear_options()
        for i, v in enumerate(remaining):
            sel.add_option((_verdict_label(v), i))
        if not remaining:
            self.query_one("#btn-add-suggestion", Button).disabled = True

        parts = []
        if added:
            parts.append(f"Agregadas: {', '.join(added)}.")
        if forced:
            parts.append(f"Forzadas pese a duplicado: {', '.join(forced)}.")
        if skipped:
            parts.append(f"Omitidas (nombre ya existe): {', '.join(skipped)}.")
        self.post_message(CategoriesChanged())

        session_id = self._selected_session_id
        if session_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] Reclasificando 'Otros'...")
        moved = await _reclassify_otros(session_id)
        fb.update(
            f"[green]{' '.join(parts)} {moved} segmento(s) reclasificado(s) desde 'Otro'.[/green]"
        )
