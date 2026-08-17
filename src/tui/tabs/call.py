"""Tab 1: Call Copilot — transcripción en vivo + sugerencias LLM."""

import asyncio
import logging
import os
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, RichLog, Select, Static, TabbedContent, TabPane

from src.tui import bootstrap
from src.i18n import t
from src.processing.session_processor import process
from src.profiles.store import ProfileStore
from src.profiles.models import CallProfile
from src.tui.screens.profile_manager import ProfileManagerScreen
from src.tui.screens.settings import SettingsScreen


def build_audio_sink_options() -> list[tuple[str, str]]:
    """
    Build (label, value) pairs for CallCopilotTab's "Salida de audio a
    capturar" Select. Value "" means "system default device" (the
    pre-existing behavior). A non-empty value identifies a specific
    device to capture: on Linux, a bare Pulse/PipeWire sink name, passed
    to PulseLoopbackSource(device=...) (which appends ".monitor" itself);
    on Windows, a WASAPI device index (as str), passed to
    WASAPILoopbackSource(device_index=int(value)).

    Only one of the two listing calls below ever returns anything —
    list_sinks() needs pactl (Linux), list_output_devices() needs
    pyaudiowpatch (Windows); each is a no-op on the other platform, so
    it's safe to just concatenate both.
    """
    from src.audio.pulse_source import list_sinks, sink_label
    from src.audio.wasapi_source import device_label, list_output_devices

    options = [(t("call.audio_sink_default"), "")]
    options.extend((sink_label(s), s.name) for s in list_sinks())
    options.extend((device_label(d), str(d.index)) for d in list_output_devices())
    return options


def _should_trigger_processing(session_id) -> bool:
    """Return True when a post-session processing run should be scheduled.

    Pure function — no side effects, easy to test without Textual.
    """
    return bool(session_id)


class CallCopilotTab(TabPane):
    def __init__(self):
        super().__init__(t("call.tab_title"), id="tab-call")
        self._pipeline = None
        self._pipeline_task = None
        # Profile state — loaded once at tab construction; refreshed after ProfileManagerScreen.
        self._profile_store = ProfileStore()
        # Active profile is snapshotted at call start (no live reload during an active call).
        self._active_profile: CallProfile = self._profile_store.get_active()
        # "" means system default device (PulseLoopbackSource(device=None) /
        # WASAPILoopbackSource(device_index=None)) — see build_audio_sink_options.
        self._audio_device: str = ""

    def compose(self) -> ComposeResult:
        # This tab's content (2x RichLog + several Selects/Inputs) easily
        # exceeds a small terminal's height. TabPane doesn't scroll on its
        # own, so without this wrapper the layout overflows into visually
        # overlapping widgets instead of just scrolling.
        with VerticalScroll():
            yield Label(t("call.session_title_label"), id="lbl-session-title")
            yield Input(placeholder=t("call.session_title_placeholder"), id="session_title")
            yield Label(t("call.context_label"), id="lbl-call-context")
            yield Input(
                placeholder=t("call.context_placeholder"),
                id="call-context",
            )
            yield Label(t("call.profile_label"), id="lbl-profile")
            profile_options = [(p.name, p.id) for p in self._profile_store.list()]
            yield Select(
                options=profile_options,
                value=self._active_profile.id,
                id="profile-select",
            )
            yield Label(t("call.audio_sink_label"), id="lbl-audio-sink")
            with Horizontal(id="audio-sink-row"):
                yield Select(
                    options=build_audio_sink_options(),
                    value="",
                    id="audio-sink-select",
                )
                yield Button("↻", id="btn-refresh-sinks", variant="default")
            with Horizontal(id="call-buttons"):
                yield Button(t("call.start_button"), id="btn-start-call", variant="success")
                yield Button(
                    t("call.stop_button"), id="btn-stop-call", variant="error", disabled=True
                )
                yield Button(
                    t("call.manage_profiles_button"), id="btn-manage-profiles", variant="default"
                )
                yield Button(t("call.settings_button"), id="btn-settings", variant="default")
            yield Label(t("call.transcript_label"), id="lbl-transcript")
            yield RichLog(id="transcript-log", highlight=True, markup=True, wrap=True)
            yield Label(t("call.suggestion_label"), id="lbl-suggestion")
            yield Static("", id="suggestion-live")
            yield RichLog(id="suggestion-log", highlight=True, markup=True, wrap=True)

    def retranslate(self) -> None:
        """
        Re-apply t() to this tab's static chrome — not the transcript/
        suggestion RichLogs (live call data) and not the typed session
        title/context Inputs (user data). The tab's own title (shown in the
        TabbedContent tab bar) is re-set via TabbedContent.get_tab(), since
        that text lives on the associated Tab widget, not on this TabPane.
        """
        self.query_one("#lbl-session-title", Label).update(t("call.session_title_label"))
        session_title = self.query_one("#session_title", Input)
        if not session_title.value:
            session_title.placeholder = t("call.session_title_placeholder")
        self.query_one("#lbl-call-context", Label).update(t("call.context_label"))
        call_context = self.query_one("#call-context", Input)
        if not call_context.value:
            call_context.placeholder = t("call.context_placeholder")
        self.query_one("#lbl-profile", Label).update(t("call.profile_label"))
        self.query_one("#lbl-audio-sink", Label).update(t("call.audio_sink_label"))
        self.query_one("#audio-sink-select", Select).set_options(build_audio_sink_options())
        self.query_one("#btn-start-call", Button).label = t("call.start_button")
        self.query_one("#btn-stop-call", Button).label = t("call.stop_button")
        self.query_one("#btn-manage-profiles", Button).label = t("call.manage_profiles_button")
        self.query_one("#btn-settings", Button).label = t("call.settings_button")
        self.query_one("#lbl-transcript", Label).update(t("call.transcript_label"))
        self.query_one("#lbl-suggestion", Label).update(t("call.suggestion_label"))
        tab = self.app.query_one(TabbedContent).get_tab("tab-call")
        tab.label = t("call.tab_title")

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
            suggestion_log.write(f"[red]{t('call.stt_error', error=e)}[/red]")
            return

        try:
            llm = bootstrap._build_llm()
            _log.info("LLM built: %s", type(llm).__name__)
        except Exception as e:
            _log.exception("_build_llm failed")
            suggestion_log.write(f"[red]{t('call.llm_error', error=e)}[/red]")
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

            device_index = int(self._audio_device) if self._audio_device else None
            _audio_source = WASAPILoopbackSource(device_index=device_index)
        elif sys.platform == "darwin":
            from src.audio.blackhole_source import BlackHoleLoopbackSource

            _audio_source = BlackHoleLoopbackSource()
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
            suggestion_log.write(f"[red]{t('call.pipeline_error', error=e)}[/red]")
        finally:
            await self._pipeline.stop()
