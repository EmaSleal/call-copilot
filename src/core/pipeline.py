"""
Orquesta el flujo completo: audio -> VAD -> STT -> trigger -> LLM -> output.
No conoce implementaciones concretas, solo las interfaces de core.interfaces.
Esto es lo que permite que WASAPI/tabCapture, Deepgram/Whisper,
Claude/GPT sean intercambiables vía config sin tocar esta clase.
"""

import asyncio
import difflib
import logging
import time
from collections import deque
from typing import Callable, Optional

from src.rag.chroma_store import RAGStore
from openai import AsyncOpenAI

_SENTENCE_END = frozenset(".?!")
_CLAUSE_END   = frozenset(",;")

from src.core.interfaces import (
    AudioSource,
    STTProvider,
    VoiceActivityDetector,
    TriggerDetector,
    TriggerEvent,
    TriggerReason,
    LLMProvider,
    LLMResponse,
    OutputSink,
    TranscriptSegment,
)
from src.output.session_logger import SessionLogger
from src.processing.live_tool_context import build_live_tool_context, detect_mentioned_tools
from src.profiles.models import CallProfile, ResponseMode
from src.profiles.heuristics import compute_conservative_mode, is_silent_mode_question
from src.llm.model_catalog import provider_of_model_id

logger = logging.getLogger("call_copilot.pipeline")


def resolve_override(model_override: str, active_provider_id: str | None) -> tuple[str, str | None]:
    """
    Offline, network-free validation of a profile's model override against
    the ACTIVE backend (read from the live provider instance, never from
    config_defaults/env — a mid-session settings save can leave them out of
    sync with the running provider object). Never hits the model catalog:
    that discovery is UI-only and must not run on the active-call hot path.

    Returns (resolved_override, notice). notice is None when no adjustment
    was needed (match, unknown prefix, or no active_provider_id to compare
    against — e.g. test doubles without a provider_id attribute).
    """
    if not model_override or active_provider_id is None:
        return model_override, None

    override_provider = provider_of_model_id(model_override)
    if override_provider is None or override_provider == active_provider_id:
        return model_override, None

    notice = (
        f"modelo de perfil '{model_override}' no corresponde al proveedor "
        f"activo '{active_provider_id}'; se descarta y se usa el default del pipeline"
    )
    return "", notice

# Meta-responses that silent mode LLMs may emit instead of real content.
# These are filtered out rather than forwarded to the output sink.
_META_RESPONSES = frozenset({
    "no respondas", "no respondas.", "skip",
    "sin respuesta", "sin respuesta.", "",
})


def _similarity_ratio(a: str, b: str) -> float:
    """Cheap local text-similarity ratio (0..1), no embeddings/API calls."""
    return difflib.SequenceMatcher(None, a, b).ratio()


class CallCopilotPipeline:
    def __init__(
        self,
        audio_source: AudioSource,
        vad: VoiceActivityDetector,
        stt: STTProvider,
        trigger: TriggerDetector,
        llm: LLMProvider,
        output: OutputSink,
        llm_enabled: bool = True,
        initial_context: str = "",
        on_segment: Optional[Callable[[TranscriptSegment], None]] = None,
        min_substantial_words: int = 40,
        openai_client: AsyncOpenAI | None = None,
        active_profile: CallProfile | None = None,
        cooldown_seconds: float = 6.0,
        dedup_threshold: float = 0.82,
    ):
        self.audio_source = audio_source
        self.vad = vad
        self.stt = stt
        self.trigger = trigger
        self.llm = llm
        self.output = output
        self.llm_enabled = llm_enabled
        self.initial_context = initial_context
        self.session_logger = SessionLogger(initial_context=initial_context)
        self.on_segment = on_segment
        self._min_substantial_words = min_substantial_words
        self._openai_client = openai_client
        # Repetition guard: paced meetings re-trigger the inactivity timer on
        # every short pause inside the same still-unfinished idea, so a flat
        # cooldown + a last-block similarity check keep near-duplicate blocks
        # from reaching the LLM twice.
        self._cooldown_seconds = cooldown_seconds
        self._dedup_threshold = dedup_threshold
        self._last_trigger_at: float = 0.0
        self._last_block_text: str = ""
        # Active profile is snapshotted at call start (no live reload).
        # To change profiles mid-call the caller must create a new pipeline instance.
        self._active_profile: CallProfile | None = active_profile

        self._running = False
        self._inactivity_task: Optional[asyncio.Task] = None
        self._inactivity_timeout: float = 2.0
        self._rag: RAGStore | None = None
        self._known_tools: list = []
        self._current_block: list[str] = []
        self._recent_words: deque[str] = deque(maxlen=300)
        # Captured on start() — used by the TUI to trigger post-session processing.
        self._session_id: Optional[int] = None

    @property
    def transcript_path(self) -> str:
        """Return the filesystem path of the current session's transcript file."""
        return str(self.session_logger.file_path)

    async def start(self, title: str = "") -> None:
        if self._running:
            return
        self._running = True

        await self.audio_source.start()
        await self.stt.connect()

        import src.db.database as db
        self._known_tools = db.get_tools()

        if self._openai_client:
            self._rag = RAGStore(
                session_id=self.session_logger.session_id,
                openai_client=self._openai_client,
            )
            cs = db.create_call_session(
                context=self.initial_context,
                transcript_path=str(self.session_logger.file_path),
                chroma_collection=self._rag.collection_name,
                profile_id=self._active_profile.id if self._active_profile else None,
                title=title,
            )
            self._session_id = cs.id

        await asyncio.gather(
            self._feed_audio_to_stt(),
            self._consume_transcripts(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._inactivity_task:
            self._inactivity_task.cancel()
        await self.audio_source.stop()
        await self.stt.close()
        self.session_logger.close()
        logger.info("sesión guardada: %s", self.session_logger.file_path)

    async def _feed_audio_to_stt(self) -> None:
        async for chunk in self.audio_source.stream():
            if not self._running:
                break
            await self.stt.send_audio(chunk)

    async def _consume_transcripts(self) -> None:
        async for segment in self.stt.transcripts():
            await self._handle_segment(segment)

    async def _inactivity_trigger(self) -> None:
        try:
            await asyncio.sleep(self._inactivity_timeout)
            await self._handle_trigger()
        except asyncio.CancelledError:
            pass

    async def _handle_segment(self, segment: TranscriptSegment) -> None:
        if not segment.is_final:
            return

        if self.on_segment:
            self.on_segment(segment)

        self._current_block.append(segment.text)
        self._recent_words.extend(segment.text.split())
        self.session_logger.log_transcript(segment.text)
        if self._rag:
            await self._rag.add_segment(segment.text)

        if self._inactivity_task:
            self._inactivity_task.cancel()

        self._inactivity_task = asyncio.create_task(self._inactivity_trigger())

    def _block_word_count(self) -> int:
        return len(" ".join(self._current_block).split())

    def _schedule_retry(self, delay: float) -> None:
        """Re-fire _handle_trigger after `delay`s without waiting on new
        segments — used when a block is ready but still inside the cooldown
        window, so it isn't silently dropped if the speaker stays quiet."""
        if self._inactivity_task:
            self._inactivity_task.cancel()

        async def _retry() -> None:
            try:
                await asyncio.sleep(delay)
                await self._handle_trigger()
            except asyncio.CancelledError:
                pass

        self._inactivity_task = asyncio.create_task(_retry())

    async def _handle_trigger(self) -> None:
        word_count = self._block_word_count()
        if word_count < self._min_substantial_words:
            logger.debug("bloque insuficiente (%d palabras < %d), esperando más", word_count, self._min_substantial_words)
            return

        block_text = " ".join(self._current_block)

        elapsed = time.monotonic() - self._last_trigger_at
        if self._cooldown_seconds > 0 and elapsed < self._cooldown_seconds:
            remaining = self._cooldown_seconds - elapsed
            logger.debug("cooldown activo (%.1fs restantes), reintentando más tarde", remaining)
            self._schedule_retry(remaining)
            return

        if self._last_block_text:
            ratio = _similarity_ratio(block_text, self._last_block_text)
            if ratio >= self._dedup_threshold:
                logger.debug(
                    "bloque %.0f%% similar al anterior, se descarta sin llamar al LLM", ratio * 100
                )
                self._current_block = []
                return

        self._current_block = []
        self._last_trigger_at = time.monotonic()
        self._last_block_text = block_text

        if self._rag:
            relevant = await self._rag.search(query=block_text, top_k=5)
            rag_context = "\n".join(relevant) if relevant else block_text
        else:
            rag_context = block_text

        # Cheap, network-free tool-mention detection (regex against the
        # catalog's normalized names) — no LLM/embedding call added to the
        # hot path. See src/processing/live_tool_context.py.
        mentioned_tools = detect_mentioned_tools(block_text, self._known_tools)
        if mentioned_tools:
            tool_context = await asyncio.to_thread(build_live_tool_context, mentioned_tools)
            if tool_context:
                rag_context = f"{rag_context}\n\n{tool_context}".strip()

        logger.debug("trigger: %d palabras → LLM", word_count)

        if not self.llm_enabled:
            return

        # Compute conservative_mode from active profile heuristics.
        # Gate lives here (not in HeuristicTriggerDetector) because this is
        # where block_text is assembled from the current block buffer.
        profile = self._active_profile
        conservative_mode = False
        system_prompt_addon = ""
        response_mode = "copilot"
        model_override = ""
        if profile is not None:
            conservative_mode = compute_conservative_mode(
                block_text, profile.heuristics
            )
            system_prompt_addon = profile.system_prompt_addon
            response_mode = profile.response_mode.value
            model_override = profile.model

            # Silent mode: strict gate — call LLM ONLY for clear short questions.
            # is_silent_mode_question requires ?, an interrogative word, and < 25 words.
            if profile.response_mode == ResponseMode.silent:
                if not is_silent_mode_question(block_text):
                    return  # skip LLM call entirely

        active_provider_id = getattr(self.llm, "provider_id", None)
        model_override, override_notice = resolve_override(model_override, active_provider_id)
        if override_notice:
            logger.warning(override_notice)

        base = f"{self.initial_context}\n\n{rag_context}".strip() if self.initial_context else rag_context
        recent_text = " ".join(self._recent_words)
        trigger_event = TriggerEvent(
            reason=TriggerReason.SILENCE_TIMEOUT,
            context_text=block_text,
            confidence=0.8,
            conservative_mode=conservative_mode,
            recent_context=recent_text,
        )
        full_response = ""
        try:
            # Silent mode buffers responses to filter meta-instructions before
            # emitting (nothing is emitted mid-stream); every other mode
            # streams each chunk to the output sink as it arrives.
            async for response in self.llm.respond(
                base,
                trigger_event,
                system_prompt_addon=system_prompt_addon,
                conservative_mode=conservative_mode,
                response_mode=response_mode,
                model_override=model_override,
            ):
                if response_mode != "silent":
                    await self.output.emit(response)
                if not response.is_partial:
                    full_response = response.text

            if response_mode == "silent" and full_response.strip().lower() not in _META_RESPONSES:
                await self.output.emit(LLMResponse(text=full_response, is_partial=False))
        except Exception as e:
            logger.error("error calling LLM: %s", e, exc_info=True)
            await self.output.emit(LLMResponse(text=f"[LLM error: {e}]", is_partial=False))

        self.session_logger.log_response(rag_context, full_response)
