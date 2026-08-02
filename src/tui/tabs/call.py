"""Tab 1: Call Copilot — transcripción en vivo + sugerencias LLM."""

import asyncio
import logging
import os
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, RichLog, Select, Static, TabPane

from src.tui import bootstrap
from src.processing.session_processor import process
from src.profiles.store import ProfileStore
from src.profiles.models import CallProfile
from src.tui.screens.profile_manager import ProfileManagerScreen
from src.tui.screens.settings import SettingsScreen


def build_audio_sink_options() -> list[tuple[str, str]]:
    """
    Build (label, value) pairs for CallCopilotTab's "Salida de audio a
    capturar" Select. Value "" means "system default sink" (the pre-existing
    behavior); a non-empty value is a bare sink name, passed as
    PulseLoopbackSource(device=...) — that class appends ".monitor" itself.

    Only meaningful on Linux; on other platforms or when pactl is
    unavailable, list_sinks() returns [] and only the default option shows.
    """
    from src.audio.pulse_source import list_sinks, sink_label

    options = [("Default (sink del sistema)", "")]
    options.extend((sink_label(s), s.name) for s in list_sinks())
    return options


def _should_trigger_processing(session_id) -> bool:
    """Return True when a post-session processing run should be scheduled.

    Pure function — no side effects, easy to test without Textual.
    """
    return bool(session_id)


class CallCopilotTab(TabPane):
    def __init__(self):
        super().__init__("📞 Call Copilot", id="tab-call")
        self._pipeline = None
        self._pipeline_task = None
        # Profile state — loaded once at tab construction; refreshed after ProfileManagerScreen.
        self._profile_store = ProfileStore()
        # Active profile is snapshotted at call start (no live reload during an active call).
        self._active_profile: CallProfile = self._profile_store.get_active()
        # "" means system default sink (PulseLoopbackSource(device=None)) — see build_audio_sink_options.
        self._audio_device: str = ""

    def compose(self) -> ComposeResult:
        yield Label("Título de la sesión (opcional):")
        yield Input(placeholder="Título de la sesión (opcional)", id="session_title")
        yield Label("Contexto de la llamada (opcional):")
        yield Input(
            placeholder="Ej: reunión de ventas con cliente enterprise",
            id="call-context",
        )
        yield Label("Perfil activo:")
        profile_options = [(p.name, p.id) for p in self._profile_store.list()]
        yield Select(
            options=profile_options,
            value=self._active_profile.id,
            id="profile-select",
        )
        yield Label(
            "Salida de audio a capturar (Linux — qué sale por la corneta/auriculares):"
        )
        with Horizontal(id="audio-sink-row"):
            yield Select(
                options=build_audio_sink_options(),
                value="",
                id="audio-sink-select",
            )
            yield Button("↻", id="btn-refresh-sinks", variant="default")
        with Horizontal(id="call-buttons"):
            yield Button("▶ Iniciar", id="btn-start-call", variant="success")
            yield Button(
                "⏹ Detener", id="btn-stop-call", variant="error", disabled=True
            )
            yield Button(
                "Gestionar perfiles", id="btn-manage-profiles", variant="default"
            )
            yield Button("⚙ Configuración", id="btn-settings", variant="default")
        yield Label("Transcripción en vivo:", id="lbl-transcript")
        yield RichLog(id="transcript-log", highlight=True, markup=True, wrap=True)
        yield Label("Sugerencia del copiloto:", id="lbl-suggestion")
        yield Static("", id="suggestion-live")
        yield RichLog(id="suggestion-log", highlight=True, markup=True, wrap=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update active profile / audio sink when the user picks a different option."""
        if event.select.id == "profile-select":
            profile = self._profile_store.get(str(event.value))
            if profile is not None:
                self._active_profile = profile
        elif event.select.id == "audio-sink-select":
            self._audio_device = str(event.value) if event.value else ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start-call":
            self._start_call()
        elif event.button.id == "btn-stop-call":
            self._stop_call()
        elif event.button.id == "btn-manage-profiles":
            self.app.push_screen(
                ProfileManagerScreen(self._profile_store), self._on_profiles_managed
            )
        elif event.button.id == "btn-settings":
            self.app.push_screen(SettingsScreen(), self._on_profiles_managed)
        elif event.button.id == "btn-refresh-sinks":
            self.query_one("#audio-sink-select", Select).set_options(
                build_audio_sink_options()
            )

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
        self._pipeline_task = asyncio.create_task(
            self._run_pipeline(context, title=title)
        )

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

        transcript_log = self.query_one("#transcript-log", RichLog)
        suggestion_log = self.query_one("#suggestion-log", RichLog)
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
            stt = bootstrap._build_stt()
            _log.info("STT built: %s", type(stt).__name__)
        except Exception as e:
            _log.exception("_build_stt failed")
            suggestion_log.write(f"[red]Error cargando STT: {e}[/red]")
            return

        try:
            llm = bootstrap._build_llm()
            _log.info("LLM built: %s", type(llm).__name__)
        except Exception as e:
            _log.exception("_build_llm failed")
            suggestion_log.write(f"[red]Error cargando LLM: {e}[/red]")
            return

        output = TUIOutput()

        from openai import AsyncOpenAI

        openai_client = (
            AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            if os.getenv("OPENAI_API_KEY")
            else None
        )

        if sys.platform == "win32":
            from src.audio.wasapi_source import WASAPILoopbackSource

            _audio_source = WASAPILoopbackSource()
        else:
            from src.audio.pulse_source import PulseLoopbackSource

            _audio_source = PulseLoopbackSource(device=self._audio_device or None)

        vad = bootstrap._silero_vad_instance
        if vad is None:
            from src.audio.vad_silero import SileroVAD
            from src.core import config_defaults

            vad = SileroVAD(silence_threshold_ms=config_defaults.silence_threshold_ms())

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
