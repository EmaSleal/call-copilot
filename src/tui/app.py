"""
TUI unificada. Corre call-copilot y video transcriber en paralelo
en el mismo proceso asyncio, con tabs separados por modo.

Tabs:
  [1] Call Copilot   — transcripción en vivo + sugerencias LLM
  [2] Video          — procesar URL de YouTube, historial de sesiones
  [3] Buscar         — search full-text en segmentos de BD
  [4] Categorías     — CRUD de taxonomía
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button, DataTable, Footer, Header, Input, Label,
    ProgressBar, RichLog, SelectionList, Static, TabbedContent, TabPane,
)

import src.db.database as db
from src.db.database import init_db

load_dotenv()


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
                yield Button("Analizar Otros", id="btn-modal-analyze", variant="warning")
                yield Button("Cerrar", id="btn-modal-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-modal-close":
            self.dismiss(None)
        elif event.button.id == "btn-modal-analyze":
            self.dismiss("analyze")


# ─────────────────────────────────────────────────────────────
# Tab 1: Call Copilot
# ─────────────────────────────────────────────────────────────

class CallCopilotTab(TabPane):
    def __init__(self):
        super().__init__("📞 Call Copilot", id="tab-call")
        self._pipeline = None
        self._pipeline_task = None

    def compose(self) -> ComposeResult:
        yield Label("Contexto de la llamada (opcional):")
        yield Input(placeholder="Ej: reunión de ventas con cliente enterprise", id="call-context")
        with Horizontal(id="call-buttons"):
            yield Button("▶ Iniciar", id="btn-start-call", variant="success")
            yield Button("⏹ Detener", id="btn-stop-call", variant="error", disabled=True)
        yield Label("Transcripción en vivo:", id="lbl-transcript")
        yield RichLog(id="transcript-log", highlight=True, markup=True, wrap=True)
        yield Label("Sugerencia del copiloto:", id="lbl-suggestion")
        yield RichLog(id="suggestion-log", highlight=True, markup=True, wrap=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start-call":
            self._start_call()
        elif event.button.id == "btn-stop-call":
            self._stop_call()

    def _start_call(self) -> None:
        context = self.query_one("#call-context", Input).value.strip()
        self.query_one("#btn-start-call").disabled = True
        self.query_one("#btn-stop-call").disabled = False
        self.query_one("#transcript-log", RichLog).clear()
        self.query_one("#suggestion-log", RichLog).clear()
        self._pipeline_task = asyncio.create_task(self._run_pipeline(context))

    def _stop_call(self) -> None:
        if self._pipeline_task:
            self._pipeline_task.cancel()
        if self._pipeline:
            asyncio.create_task(self._pipeline.stop())
        self.query_one("#btn-start-call").disabled = False
        self.query_one("#btn-stop-call").disabled = True
        self._pipeline = None

    async def _run_pipeline(self, context: str) -> None:
        from src.audio.wasapi_source import WASAPILoopbackSource
        from src.audio.vad_silero import SileroVAD
        from src.core.pipeline import CallCopilotPipeline
        from src.trigger.heuristic import HeuristicTriggerDetector
        from src.core.interfaces import LLMResponse, TranscriptSegment

        transcript_log  = self.query_one("#transcript-log",  RichLog)
        suggestion_log  = self.query_one("#suggestion-log",  RichLog)

        class TUIOutput:
            async def emit(self, response: LLMResponse):
                if response.is_partial:
                    suggestion_log.write(response.text, end="")
                else:
                    suggestion_log.write("\n[dim]─────────────────────────────[/dim]")

        def on_segment(segment: TranscriptSegment) -> None:
            ts = datetime.now().strftime("%H:%M:%S")
            transcript_log.write(f"[dim]{ts}[/dim] {segment.text}")

        stt    = _build_stt()
        llm    = _build_llm()
        output = TUIOutput()

        self._pipeline = CallCopilotPipeline(
            audio_source=WASAPILoopbackSource(),
            vad=SileroVAD(silence_threshold_ms=2000),
            stt=stt,
            trigger=HeuristicTriggerDetector(min_words=3),
            llm=llm,
            output=output,
            llm_enabled=os.getenv("LLM_ENABLED", "true").lower() == "true",
            initial_context=context,
            on_segment=on_segment,
        )

        try:
            await self._pipeline.start()
        except asyncio.CancelledError:
            pass
        finally:
            await self._pipeline.stop()


# ─────────────────────────────────────────────────────────────
# Tab 2: Video Transcriber
# ─────────────────────────────────────────────────────────────

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
        if action == "analyze" and self._selected_session_id is not None:
            asyncio.create_task(self._analyze_others(self._selected_session_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-process-video":
            url = self.query_one("#video-url", Input).value.strip()
            if url:
                asyncio.create_task(self._process_video(url))
        elif event.button.id == "btn-add-suggestion":
            self._add_selected_suggestions()

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
            otros = next((c for c in categories if c.name.lower() in ("otro", "otros")), None)
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

    def _add_selected_suggestions(self) -> None:
        sel = self.query_one("#suggestions-list", SelectionList)
        fb  = self.query_one("#suggestion-feedback", Label)
        selected_indices = sel.selected
        if not selected_indices:
            fb.update("[yellow]Marcá al menos una sugerencia antes de agregar.[/yellow]")
            return
        added = []
        for idx in selected_indices:
            if idx < len(self._suggestions):
                s = self._suggestions[idx]
                db.create_category(s["name"], s["description"])
                added.append(s["name"])
        remaining = [s for i, s in enumerate(self._suggestions) if i not in set(selected_indices)]
        self._suggestions = remaining
        sel.clear_options()
        for i, s in enumerate(remaining):
            sel.add_option((f"{s['name']} — {s['description']}", i))
        if not remaining:
            self.query_one("#btn-add-suggestion", Button).disabled = True
        names = ", ".join(f"'{n}'" for n in added)
        fb.update(f"[green]Agregadas: {names}.[/green]")


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
    RichLog { height: 12; border: solid #334155; background: #1e293b; padding: 0 1; }
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
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Salir"),
        Binding("1", "switch_tab('tab-call')",        "Call Copilot"),
        Binding("2", "switch_tab('tab-video')",       "Video"),
        Binding("3", "switch_tab('tab-search')",      "Buscar"),
        Binding("4", "switch_tab('tab-categories')",  "Categorías"),
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
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id


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
    from src.stt.whisper_local_provider import WhisperLocalSTT
    return WhisperLocalSTT(model_size="large-v3-turbo", device="cuda", language="es")


def _build_llm():
    backend = os.getenv("LLM_BACKEND", "gpt")
    if backend == "gpt":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=os.getenv("OPENAI_API_KEY"),
            token_threshold=int(os.getenv("LLM_TOKEN_THRESHOLD", "500"))
        )
    from src.llm.claude_provider import ClaudeProvider
    return ClaudeProvider(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

def main():
    init_db()
    UnifiedApp().run()


if __name__ == "__main__":
    main()
