"""
TUI unificada. Corre call-copilot y video transcriber en paralelo
en el mismo proceso asyncio, con tabs separados por modo.

Tabs:
  [1] Call Copilot   — transcripción en vivo + sugerencias LLM
  [2] Video          — procesar URL de YouTube, historial de sesiones
  [3] Buscar         — search full-text en segmentos de BD
  [4] Categorías     — CRUD de taxonomía
  [5] Historial      — navegar sesiones de llamada pasadas e ideas extraídas
"""

import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    ProgressBar, RichLog, Select, SelectionList, Static, TabbedContent, TabPane,
)

import src.db.database as db
from src.db.database import init_db
from src.processing.session_processor import process
from src.profiles.store import ProfileStore
from src.profiles.models import CallProfile, ResponseMode, AVAILABLE_MODELS

load_dotenv()

_log_file = os.getenv("CALL_LOG")
if _log_file:
    _fh = logging.FileHandler(_log_file, mode="a")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_fh)
    logging.getLogger().setLevel(logging.DEBUG)


def _should_trigger_processing(session_id) -> bool:
    """Return True when a post-session processing run should be scheduled.

    Pure function — no side effects, easy to test without Textual.
    """
    return bool(session_id)


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


def _find_otro_category(categories: list):
    """Locate the fallback 'Otro'/'Otros' category by name, case-insensitive.

    Pure function — no side effects, easy to test without Textual.
    """
    return next((c for c in categories if c.name.lower() in ("otro", "otros")), None)


def _partition_new_suggestions(
    suggestions: list[dict], existing_names: set[str]
) -> tuple[list[dict], list[dict]]:
    """Split suggestions into (new_ones, duplicates) by exact category name match.

    Pure function — no side effects, easy to test without Textual. Needed
    because create_category() raises on a UNIQUE name collision, and the LLM
    suggester can re-suggest a category that was already added earlier.
    """
    new_ones, duplicates = [], []
    for s in suggestions:
        (duplicates if s["name"] in existing_names else new_ones).append(s)
    return new_ones, duplicates


class CategoriesChanged(Message):
    """Posted when a category is created or deleted from any tab."""


# ─────────────────────────────────────────────────────────────
# Modal: detalle de sesión de video
# ─────────────────────────────────────────────────────────────

class SessionModal(ModalScreen):
    CSS = """
    SessionModal { align: center middle; }
    #modal-dialog {
        width: 72; height: auto;
        background: #1e293b; border: solid #4f46e5;
        padding: 2 3;
    }
    #modal-title  { text-style: bold; color: #f8fafc; margin-bottom: 1; }
    #modal-status { margin-bottom: 0; }
    #modal-meta   { color: #64748b; margin-bottom: 2; }
    #modal-actions { height: auto; margin-top: 1; }
    """

    def __init__(self, title: str, status: str, url: str, date: str, n_segs: int):
        super().__init__()
        self._title  = title
        self._status = status
        self._url    = url
        self._date   = date
        self._n_segs = n_segs

    def compose(self) -> ComposeResult:
        status_color = {"done": "green", "error": "red", "processing": "yellow"}.get(
            self._status, "white"
        )
        with Vertical(id="modal-dialog"):
            yield Label(self._title[:65], id="modal-title")
            yield Label(
                f"[{status_color}]{self._status}[/{status_color}]  •  "
                f"{self._n_segs} segmentos  •  {self._date}",
                id="modal-status",
            )
            yield Label(self._url[:65], id="modal-meta")
            with Horizontal(id="modal-actions"):
                yield Button("Analizar Otros",  id="btn-modal-analyze",    variant="warning")
                yield Button("Reprocesar",       id="btn-modal-reprocess",  variant="primary")
                yield Button("Eliminar",         id="btn-modal-delete",     variant="error")
                yield Button("Cerrar",           id="btn-modal-close",      variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-close":
            self.dismiss(None)
        elif event.button.id == "btn-modal-analyze":
            self.dismiss("analyze")
        elif event.button.id == "btn-modal-reprocess":
            self.dismiss("reprocess")
        elif event.button.id == "btn-modal-delete":
            self.dismiss("delete")


# ─────────────────────────────────────────────────────────────
# Tab 1: Call Copilot
# ─────────────────────────────────────────────────────────────

class CallCopilotTab(TabPane):
    def __init__(self):
        super().__init__("📞 Call Copilot", id="tab-call")
        self._pipeline = None
        self._pipeline_task = None
        # Profile state — loaded once at tab construction; refreshed after ProfileManagerScreen.
        self._profile_store = ProfileStore()
        # Active profile is snapshotted at call start (no live reload during an active call).
        self._active_profile: CallProfile = self._profile_store.get_active()

    def compose(self) -> ComposeResult:
        yield Label("Título de la sesión (opcional):")
        yield Input(placeholder="Título de la sesión (opcional)", id="session_title")
        yield Label("Contexto de la llamada (opcional):")
        yield Input(placeholder="Ej: reunión de ventas con cliente enterprise", id="call-context")
        yield Label("Perfil activo:")
        profile_options = [(p.name, p.id) for p in self._profile_store.list()]
        yield Select(
            options=profile_options,
            value=self._active_profile.id,
            id="profile-select",
        )
        with Horizontal(id="call-buttons"):
            yield Button("▶ Iniciar", id="btn-start-call", variant="success")
            yield Button("⏹ Detener", id="btn-stop-call", variant="error", disabled=True)
            yield Button("Gestionar perfiles", id="btn-manage-profiles", variant="default")
        yield Label("Transcripción en vivo:", id="lbl-transcript")
        yield RichLog(id="transcript-log", highlight=True, markup=True, wrap=True)
        yield Label("Sugerencia del copiloto:", id="lbl-suggestion")
        yield Static("", id="suggestion-live")
        yield RichLog(id="suggestion-log", highlight=True, markup=True, wrap=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update active profile when the user picks a different option."""
        if event.select.id == "profile-select":
            profile = self._profile_store.get(str(event.value))
            if profile is not None:
                self._active_profile = profile

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start-call":
            self._start_call()
        elif event.button.id == "btn-stop-call":
            self._stop_call()
        elif event.button.id == "btn-manage-profiles":
            self.app.push_screen(ProfileManagerScreen(self._profile_store), self._on_profiles_managed)

    def _on_profiles_managed(self, _result) -> None:
        """Called when ProfileManagerScreen dismisses; refresh the Select options."""
        # Reload the store in case profiles were added, edited, or deleted.
        self._profile_store = ProfileStore()
        self._active_profile = self._profile_store.get_active()
        try:
            selector = self.query_one("#profile-select", Select)
            new_options = [(p.name, p.id) for p in self._profile_store.list()]
            selector.set_options(new_options)
        except Exception:
            pass  # If the widget isn't mounted yet, nothing to refresh.

    def _start_call(self) -> None:
        context = self.query_one("#call-context", Input).value.strip()
        title = self.query_one("#session_title", Input).value.strip()
        self.query_one("#btn-start-call").disabled = True
        self.query_one("#btn-stop-call").disabled = False
        self.query_one("#transcript-log", RichLog).clear()
        self.query_one("#suggestion-log", RichLog).clear()
        self._pipeline_task = asyncio.create_task(self._run_pipeline(context, title=title))

    def _stop_call(self) -> None:
        pipeline = self._pipeline
        if self._pipeline_task:
            self._pipeline_task.cancel()
        if pipeline:
            asyncio.create_task(pipeline.stop())
            if _should_trigger_processing(pipeline._session_id):
                asyncio.get_running_loop().run_in_executor(
                    None, process, pipeline._session_id, pipeline.transcript_path
                )
        self.query_one("#btn-start-call").disabled = False
        self.query_one("#btn-stop-call").disabled = True
        self._pipeline = None

    async def _run_pipeline(self, context: str, title: str = "") -> None:
        _log = logging.getLogger("call_copilot.tui")
        _log.info("_run_pipeline started")
        import sys
        from src.core.pipeline import CallCopilotPipeline
        from src.trigger.heuristic import HeuristicTriggerDetector
        from src.core.interfaces import LLMResponse, TranscriptSegment

        transcript_log  = self.query_one("#transcript-log",  RichLog)
        suggestion_log  = self.query_one("#suggestion-log",  RichLog)
        suggestion_live = self.query_one("#suggestion-live", Static)

        class TUIOutput:
            def __init__(self):
                self._buf = ""

            async def emit(self, response: LLMResponse):
                if response.is_partial:
                    self._buf += response.text
                    suggestion_live.update(self._buf)
                else:
                    if self._buf:
                        suggestion_log.write(self._buf)
                        self._buf = ""
                    elif response.text:
                        # error responses arrive as non-partial with no prior chunks
                        suggestion_log.write(f"[red]{response.text}[/red]")
                    suggestion_log.write("[dim]─────────────────────────────[/dim]")
                    suggestion_live.update("")

        def on_segment(segment: TranscriptSegment) -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            transcript_log.write(f"[dim]{ts}[/dim] {segment.text}")

        try:
            stt = _build_stt()
            _log.info("STT built: %s", type(stt).__name__)
        except Exception as e:
            _log.exception("_build_stt failed")
            suggestion_log.write(f"[red]Error cargando STT: {e}[/red]")
            return

        try:
            llm = _build_llm()
            _log.info("LLM built: %s", type(llm).__name__)
        except Exception as e:
            _log.exception("_build_llm failed")
            suggestion_log.write(f"[red]Error cargando LLM: {e}[/red]")
            return

        output = TUIOutput()

        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

        if sys.platform == "win32":
            from src.audio.wasapi_source import WASAPILoopbackSource
            _audio_source = WASAPILoopbackSource()
        else:
            from src.audio.pulse_source import PulseLoopbackSource
            _audio_source = PulseLoopbackSource()

        vad = _silero_vad_instance
        if vad is None:
            from src.audio.vad_silero import SileroVAD
            vad = SileroVAD(silence_threshold_ms=2000)

        # Snapshot the active profile at call start — no live reload during the call.
        active_profile = self._active_profile

        self._pipeline = CallCopilotPipeline(
            audio_source=_audio_source,
            vad=vad,
            stt=stt,
            trigger=HeuristicTriggerDetector(min_words=3),
            llm=llm,
            output=output,
            llm_enabled=os.getenv("LLM_ENABLED", "true").lower() == "true",
            initial_context=context,
            on_segment=on_segment,
            openai_client=openai_client,
            active_profile=active_profile,
        )

        try:
            await self._pipeline.start(title=title)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            suggestion_log.write(f"[red]Error en pipeline: {e}[/red]")
        finally:
            await self._pipeline.stop()


# ─────────────────────────────────────────────────────────────
# Tab 2: Video Transcriber
# ─────────────────────────────────────────────────────────────

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
            yield Button("Agregar seleccionadas", id="btn-add-suggestion", variant="success", disabled=True)
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
                str(s.id), s.title[:50], s.status,
                s.created_at[:16], str(n_segs),
                key=str(s.id)
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "sessions-table":
            session_id = int(event.row_key.value)
            self._selected_session_id = session_id
            self._selected_suggestion_idx = None
            session, n_segs = self._sessions_cache.get(session_id, (None, 0))
            if session:
                self.app.push_screen(
                    SessionModal(session.title, session.status, session.url, session.created_at[:16], n_segs),
                    self._on_modal_action,
                )
    def _on_modal_action(self, action: str | None) -> None:
        sid = self._selected_session_id
        if sid is None or action is None:
            return
        if action == "analyze":
            asyncio.create_task(self._analyze_others(sid))
        elif action == "delete":
            db.delete_video_session(sid)
            session_dir = Path("data/videos") / str(sid)
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
        status_lbl   = self.query_one("#video-status",   Label)
        btn          = self.query_one("#btn-process-video", Button)
        btn.disabled = True
        btn.label = "⏳ Procesando..."

        def on_progress(msg: str, pct: float):
            # callback desde el thread del executor — actualizamos via call_from_thread
            self.app.call_from_thread(progress_bar.update, progress=int(pct * 100))
            self.app.call_from_thread(status_lbl.update, msg)

        try:
            loop = asyncio.get_running_loop()
            model_size = os.getenv("WHISPER_MODEL", "base")
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

        fb      = self.query_one("#suggestion-feedback", Label)
        sel     = self.query_one("#suggestions-list", SelectionList)
        btn_add = self.query_one("#btn-add-suggestion", Button)
        fb.update("Analizando segmentos 'Otros'...")

        try:
            categories = db.get_categories()
            otros = _find_otro_category(categories)
            segments = db.get_segments_by_category(session_id, otros.id if otros else None)

            if not segments:
                fb.update("[yellow]No hay segmentos 'Otros' en esta sesión.[/yellow]")
                return

            loop = asyncio.get_running_loop()
            texts = [s.text for s in segments]
            suggestions = await loop.run_in_executor(
                None, lambda: suggest_new_categories(texts, categories)
            )
            self._suggestions = suggestions
            sel.clear_options()
            btn_add.disabled = True
            if suggestions:
                for i, s in enumerate(suggestions):
                    sel.add_option((f"{s['name']} — {s['description']}", i))
                btn_add.disabled = False
                fb.update(f"[green]{len(suggestions)} sugerencia(s). Marcá las que querés agregar.[/green]")
            else:
                fb.update("[yellow]No se encontraron patrones recurrentes.[/yellow]")
        except Exception as e:
            fb.update(f"[red]Error al analizar: {e}[/red]")

    async def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#suggestions-list", SelectionList)
        fb  = self.query_one("#suggestion-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update("[yellow]Marcá al menos una sugerencia antes de agregar.[/yellow]")
            return

        existing_names = {c.name for c in db.get_categories()}
        selected = [self._suggestions[i] for i in selected_indices if i < len(self._suggestions)]
        new_ones, duplicates = _partition_new_suggestions(selected, existing_names)

        for s in new_ones:
            db.create_category(s["name"], s["description"])

        remaining = [s for i, s in enumerate(self._suggestions) if i not in set(selected_indices)]
        self._suggestions = remaining
        sel.clear_options()
        for i, s in enumerate(remaining):
            sel.add_option((f"{s['name']} — {s['description']}", i))
        if not remaining:
            self.query_one("#btn-add-suggestion", Button).disabled = True

        parts = []
        if new_ones:
            parts.append(f"Agregadas: {', '.join(s['name'] for s in new_ones)}.")
        if duplicates:
            parts.append(f"Ya existían (omitidas): {', '.join(s['name'] for s in duplicates)}.")
        self.post_message(CategoriesChanged())

        session_id = self._selected_session_id
        if session_id is None:
            fb.update(f"[green]{' '.join(parts)}[/green]" if parts else "")
            return

        fb.update(f"[green]{' '.join(parts)}[/green] Reclasificando 'Otros'...")
        moved = await _reclassify_otros(session_id)
        fb.update(f"[green]{' '.join(parts)} {moved} segmento(s) reclasificado(s) desde 'Otro'.[/green]")


# ─────────────────────────────────────────────────────────────
# Tab 3: Búsqueda
# ─────────────────────────────────────────────────────────────

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
            start  = _fmt_ts(r["start_s"])
            cat    = r.get("cat_name") or "—"
            text   = r["text"][:80] + ("…" if len(r["text"]) > 80 else "")
            title  = (r.get("session_title") or "")[:30]
            table.add_row(title, start, cat, text)


# ─────────────────────────────────────────────────────────────
# Tab 4: Categorías (CRUD)
# ─────────────────────────────────────────────────────────────

class CategoriesTab(TabPane):
    def __init__(self):
        super().__init__("🏷  Categorías", id="tab-categories")
        self._selected_id = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="cat-layout"):
            with Vertical(id="cat-list-panel"):
                yield Label("Categorías existentes")
                yield DataTable(id="cat-table")
                with Horizontal():
                    yield Button("+ Nueva", id="btn-new-cat",    variant="success")
                    yield Button("Editar",  id="btn-edit-cat",   variant="default", disabled=True)
                    yield Button("Borrar",  id="btn-delete-cat", variant="error",   disabled=True)
            with Vertical(id="cat-form-panel"):
                yield Label("Nombre:")
                yield Input(id="cat-name", placeholder="Ej: Marketing")
                yield Label("Descripción:")
                yield Input(id="cat-desc", placeholder="Descripción breve")
                yield Label("Color (hex):")
                yield Input(id="cat-color", placeholder="#6366f1", value="#6366f1")
                with Horizontal():
                    yield Button("Guardar", id="btn-save-cat", variant="primary")
                    yield Button("Cancelar", id="btn-cancel-cat", variant="default")
                yield Label("", id="cat-feedback")

    def on_mount(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Nombre", "Color", "Descripción")
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#cat-table", DataTable)
        table.clear()
        for c in db.get_categories():
            table.add_row(str(c.id), c.name, c.color, c.description[:40], key=str(c.id))
        self._selected_id = None
        self._toggle_edit_buttons(False)

    def _toggle_edit_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-edit-cat",   Button).disabled = not enabled
        self.query_one("#btn-delete-cat", Button).disabled = not enabled

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "cat-table":
            self._selected_id = int(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-new-cat":
            self._clear_form()
            self._selected_id = None
        elif bid == "btn-edit-cat" and self._selected_id:
            cats = {c.id: c for c in db.get_categories()}
            cat  = cats.get(self._selected_id)
            if cat:
                self.query_one("#cat-name",  Input).value = cat.name
                self.query_one("#cat-desc",  Input).value = cat.description
                self.query_one("#cat-color", Input).value = cat.color
        elif bid == "btn-delete-cat" and self._selected_id:
            db.delete_category(self._selected_id)
            self._refresh()
            self.query_one("#cat-feedback", Label).update("[green]Categoría eliminada.[/green]")
        elif bid == "btn-save-cat":
            self._save()
        elif bid == "btn-cancel-cat":
            self._clear_form()

    def _save(self) -> None:
        name  = self.query_one("#cat-name",  Input).value.strip()
        desc  = self.query_one("#cat-desc",  Input).value.strip()
        color = self.query_one("#cat-color", Input).value.strip() or "#6366f1"
        fb    = self.query_one("#cat-feedback", Label)
        if not name:
            fb.update("[red]El nombre no puede estar vacío.[/red]")
            return
        if self._selected_id:
            db.update_category(self._selected_id, name, desc, color)
            fb.update("[green]Categoría actualizada.[/green]")
        else:
            db.create_category(name, desc, color)
            fb.update("[green]Categoría creada.[/green]")
        self._refresh()
        self._clear_form()

    def _clear_form(self) -> None:
        self.query_one("#cat-name",  Input).value = ""
        self.query_one("#cat-desc",  Input).value = ""
        self.query_one("#cat-color", Input).value = "#6366f1"


# ─────────────────────────────────────────────────────────────
# Tab 5: Historial — browse past call sessions and their ideas
# ─────────────────────────────────────────────────────────────

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

    def compose(self) -> ComposeResult:
        yield Label("Sesiones:")
        yield DataTable(id="historial-sessions-table")
        yield Label("Fragmentos:", id="lbl-historial-ideas")
        yield DataTable(id="historial-ideas-table")
        yield Label("", id="historial-status")

    def on_mount(self) -> None:
        self._setup_tables()
        self._load_categories()
        self._refresh_sessions()

    def _load_categories(self) -> None:
        self._categories_cache = {c.id: c.name for c in db.get_categories()}

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
                str(s.id), source_label, s.title, date_display,
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
            cat_label = self._categories_cache.get(frag.category_id, "—") if frag.category_id else "—"
            ideas_table.add_row(str(i), excerpt, cat_label)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "historial-sessions-table":
            source, session_id = _parse_session_row_key(event.row_key.value)
            self._selected_source = source
            self._selected_session_id = session_id
            self._load_ideas_for_session(source, session_id)


# ─────────────────────────────────────────────────────────────
# Modal: Profile Manager Screen
# NOTE: ProfileManagerScreen is a ModalScreen, NOT a new TabPane.
# It is launched from the Call tab via push_screen() and dismissed on close.
# ─────────────────────────────────────────────────────────────

class ProfileManagerScreen(ModalScreen):
    """
    CRUD screen for call profiles, mirroring the CategoriesTab pattern:
    - Left panel: list of existing profiles (DataTable) + action buttons.
    - Right panel: create/edit form (Input fields) + save/cancel buttons.

    Launched as a ModalScreen from the "Gestionar perfiles" button in
    CallCopilotTab.  On dismiss, the caller refreshes the profile Select widget.
    """

    CSS = """
    ProfileManagerScreen { align: center middle; }
    #pm-dialog {
        width: 90; height: 42;
        background: #1e293b; border: solid #4f46e5;
        padding: 1 2;
    }
    #pm-header { height: auto; align: left middle; margin-bottom: 1; }
    #pm-title { text-style: bold; color: #f8fafc; width: 1fr; }
    #btn-pm-close { width: auto; }
    #pm-layout { height: 1fr; }
    #pm-list-panel { width: 50%; padding-right: 2; }
    #pm-form-panel { width: 50%; border-left: solid #334155; padding-left: 2; }
    #pm-table { height: 10; border: solid #334155; background: #0f172a; }
    #pm-feedback { margin-top: 1; }
    """

    def __init__(self, store: ProfileStore) -> None:
        super().__init__()
        self._store = store
        self._selected_id: str | None = None

    BINDINGS = [("escape", "close", "Cerrar")]

    def action_close(self) -> None:
        self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical(id="pm-dialog"):
            with Horizontal(id="pm-header"):
                yield Label("Gestionar perfiles", id="pm-title")
                yield Button("✕ Cerrar", id="btn-pm-close", variant="default")
            with Horizontal(id="pm-layout"):
                with Vertical(id="pm-list-panel"):
                    yield Label("Perfiles existentes")
                    yield DataTable(id="pm-table")
                    with Horizontal():
                        yield Button("+ Nuevo",  id="btn-pm-new",    variant="success")
                        yield Button("Editar",   id="btn-pm-edit",   variant="default", disabled=True)
                        yield Button("Borrar",   id="btn-pm-delete", variant="error",   disabled=True)
                    yield Label("", id="pm-feedback")
                with Vertical(id="pm-form-panel"):
                    yield Label("Nombre:")
                    yield Input(id="pm-name",   placeholder="Ej: Negociación")
                    yield Label("Descripción:")
                    yield Input(id="pm-desc",   placeholder="Descripción breve")
                    yield Label("Addon de sistema (opcional):")
                    yield Input(id="pm-addon",  placeholder="Instrucción extra para el LLM")
                    yield Label("Modo de respuesta:")
                    yield Select(
                        [(mode.value, mode.value) for mode in ResponseMode],
                        id="pm-response-mode",
                        value="copilot",
                    )
                    yield Label("Modelo:")
                    yield Select(
                        [(label, model_id) for model_id, label in AVAILABLE_MODELS],
                        id="pm-model",
                        value="",
                    )
                    yield Button("Guardar", id="btn-pm-save", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one("#pm-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "Nombre", "Addon")
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#pm-table", DataTable)
        table.clear()
        for p in self._store.list():
            addon_preview = (p.system_prompt_addon[:25] + "…") if len(p.system_prompt_addon) > 25 else p.system_prompt_addon
            table.add_row(p.id, p.name, addon_preview, key=p.id)
        self._selected_id = None
        self._toggle_edit_buttons(False)

    def _toggle_edit_buttons(self, enabled: bool) -> None:
        self.query_one("#btn-pm-edit",   Button).disabled = not enabled
        self.query_one("#btn-pm-delete", Button).disabled = not enabled

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "pm-table" and event.row_key is not None:
            self._selected_id = str(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "pm-table":
            self._selected_id = str(event.row_key.value)
            self._toggle_edit_buttons(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-pm-new":
            self._clear_form()
            self._selected_id = None
        elif bid == "btn-pm-edit" and self._selected_id:
            profile = self._store.get(self._selected_id)
            if profile:
                self.query_one("#pm-name",  Input).value = profile.name
                self.query_one("#pm-desc",  Input).value = profile.description
                self.query_one("#pm-addon", Input).value = profile.system_prompt_addon
                self.query_one("#pm-response-mode", Select).value = profile.response_mode.value
                self.query_one("#pm-model", Select).value = profile.model
        elif bid == "btn-pm-delete" and self._selected_id:
            self._delete_selected()
        elif bid == "btn-pm-save":
            self._save()
        elif bid == "btn-pm-close":
            self.dismiss(None)

    def _delete_selected(self) -> None:
        fb = self.query_one("#pm-feedback", Label)
        profiles = self._store.list()
        if len(profiles) <= 1:
            fb.update("[red]No se puede borrar el último perfil.[/red]")
            return
        self._store.delete(self._selected_id)
        self._refresh()
        fb.update("[green]Perfil eliminado.[/green]")

    def _save(self) -> None:
        from src.profiles.models import ProfileHeuristics, CallProfile as _CP
        import uuid
        name  = self.query_one("#pm-name",  Input).value.strip()
        desc  = self.query_one("#pm-desc",  Input).value.strip()
        addon = self.query_one("#pm-addon", Input).value.strip()
        fb    = self.query_one("#pm-feedback", Label)
        raw_mode = self.query_one("#pm-response-mode", Select).value
        try:
            response_mode = ResponseMode(str(raw_mode))
        except (ValueError, TypeError):
            response_mode = ResponseMode.copilot
        raw_model = self.query_one("#pm-model", Select).value
        model = str(raw_model) if raw_model and str(raw_model) != "None" else ""
        if not name:
            fb.update("[red]El nombre no puede estar vacío.[/red]")
            return
        if self._selected_id:
            existing = self._store.get(self._selected_id)
            if existing:
                updated = _CP(
                    id=self._selected_id,
                    name=name,
                    description=desc,
                    system_prompt_addon=addon,
                    heuristics=existing.heuristics,
                    response_mode=response_mode,
                    model=model,
                )
                self._store.update(updated)
                fb.update("[green]Perfil actualizado.[/green]")
        else:
            new_id = name.lower().replace(" ", "_")
            # Avoid collisions with a uuid suffix when id already exists
            if self._store.get(new_id):
                new_id = f"{new_id}_{uuid.uuid4().hex[:6]}"
            new_profile = _CP(
                id=new_id,
                name=name,
                description=desc,
                system_prompt_addon=addon,
                heuristics=ProfileHeuristics(),
                response_mode=response_mode,
                model=model,
            )
            self._store.add(new_profile)
            fb.update("[green]Perfil creado.[/green]")
        self._refresh()
        self._clear_form()

    def _clear_form(self) -> None:
        self.query_one("#pm-name",  Input).value = ""
        self.query_one("#pm-desc",  Input).value = ""
        self.query_one("#pm-addon", Input).value = ""
        self.query_one("#pm-response-mode", Select).value = "copilot"
        self.query_one("#pm-model", Select).value = ""


# ─────────────────────────────────────────────────────────────
# App principal
# ─────────────────────────────────────────────────────────────

class UnifiedApp(App):
    CSS = """
    Screen { background: #0f172a; }
    Header { background: #1e293b; color: #f8fafc; }
    Footer { background: #1e293b; color: #64748b; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }
    Input { margin-bottom: 1; }
    Label { color: #94a3b8; margin-bottom: 0; }
    Button { margin-right: 1; }
    RichLog { height: 10; border: solid #334155; background: #1e293b; padding: 0 1; }
    #suggestion-live { height: 5; border: dashed #4f46e5; background: #1e1e2e; padding: 0 1; color: #e2e8f0; }
    DataTable { height: 15; border: solid #334155; background: #1e293b; }
    #call-buttons { margin-bottom: 1; }
    #cat-layout { height: 1fr; }
    #cat-list-panel { width: 50%; padding-right: 2; }
    #cat-form-panel { width: 50%; border-left: solid #334155; padding-left: 2; }
    ProgressBar { margin: 1 0; }
    #video-status { margin-bottom: 1; }
    #lbl-sessions { margin-bottom: 1; }
    #suggestions-list { height: 8; border: solid #334155; background: #1e293b; }
    #suggestion-feedback { margin-top: 1; }
    #tab-video Horizontal { height: auto; }
    #tab-video Horizontal Input { width: 1fr; }
    #tab-search Horizontal { height: auto; }
    #tab-search Horizontal Input { width: 1fr; }
    Select { margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Salir"),
        Binding("1", "switch_tab('tab-call')",        "Call Copilot"),
        Binding("2", "switch_tab('tab-video')",       "Video"),
        Binding("3", "switch_tab('tab-search')",      "Buscar"),
        Binding("4", "switch_tab('tab-categories')",  "Categorías"),
        Binding("5", "switch_tab('tab-historial')",   "Historial"),
    ]

    TITLE = "Unified Copilot"
    SUB_TITLE = "Call Copilot + Video Transcriber"

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            yield CallCopilotTab()
            yield VideoTab()
            yield SearchTab()
            yield CategoriesTab()
            yield HistorialTab()
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def on_categories_changed(self, event: CategoriesChanged) -> None:
        self.query_one(CategoriesTab)._refresh()


# ─────────────────────────────────────────────────────────────
# Helpers compartidos
# ─────────────────────────────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def _build_stt():
    backend = os.getenv("STT_BACKEND", "deepgram")
    if backend == "deepgram":
        from src.stt.deepgram_provider import DeepgramSTT
        return DeepgramSTT(api_key=os.getenv("DEEPGRAM_API_KEY"), language="es")
    if _whisper_stt_instance is not None:
        return _whisper_stt_instance
    from src.stt.whisper_local_provider import WhisperLocalSTT
    model_size = os.getenv("WHISPER_MODEL", "large-v3-turbo")
    return WhisperLocalSTT(model_size=model_size, device="cuda", language="es")


def _build_llm():
    backend = os.getenv("LLM_BACKEND", "claude")
    if backend == "gpt":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=os.getenv("OPENAI_API_KEY"),
            token_threshold=int(os.getenv("LLM_TOKEN_THRESHOLD", "500"))
        )
    # "claude" is the default; "ollama" is not supported for the copilot LLM
    # (Ollama is used in the video classifier, not for real-time streaming)
    from src.llm.claude_provider import ClaudeProvider
    return ClaudeProvider(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

_whisper_stt_instance = None
_silero_vad_instance = None


def _preload_models() -> None:
    """Load all heavy models before Textual opens the terminal.

    tqdm + Python 3.14 + Textual's open file descriptors conflict when
    multiprocessing tries to fork a resource tracker. torch.hub.load also
    blocks. Running everything here avoids freezing the Textual event loop.
    """
    global _whisper_stt_instance, _silero_vad_instance

    backend = os.getenv("STT_BACKEND", "deepgram")
    if backend == "whisper_local":
        from src.stt.whisper_local_provider import WhisperLocalSTT
        model_size = os.getenv("WHISPER_MODEL", "large-v3-turbo")
        print(f"Loading Whisper model '{model_size}'...")
        _whisper_stt_instance = WhisperLocalSTT(model_size=model_size, device="cuda", language="es")
        print("Whisper ready.")

    print("Loading Silero VAD...")
    from src.audio.vad_silero import SileroVAD
    _silero_vad_instance = SileroVAD(silence_threshold_ms=2000)
    print("VAD ready.")


def main():
    init_db()
    _preload_models()
    UnifiedApp().run()


if __name__ == "__main__":
    main()
