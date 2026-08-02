"""
Orquesta el flujo completo: audio -> VAD -> STT -> trigger -> LLM -> output.
No conoce implementaciones concretas, solo las interfaces de core.interfaces.
Esto es lo que permite que WASAPI/tabCapture, Deepgram/Whisper,
Claude/GPT sean intercambiables vía config sin tocar esta clase.
"""

import asyncio
import logging
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
    OutputSink,
    TranscriptSegment,
)
from src.output.session_logger import SessionLogger
from src.profiles.models import CallProfile, ResponseMode
from src.profiles.heuristics import compute_conservative_mode, is_silent_mode_question

logger = logging.getLogger("call_copilot.pipeline")

# Meta-responses that silent mode LLMs may emit instead of real content.
# These are filtered out rather than forwarded to the output sink.
_META_RESPONSES = frozenset({
    "no respondas", "no respondas.", "skip",
    "sin respuesta", "sin respuesta.", "",
})


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
        # Active profile is snapshotted at call start (no live reload).
        # To change profiles mid-call the caller must create a new pipeline instance.
        self._active_profile: CallProfile | None = active_profile

        self._running = False
        self._inactivity_task: Optional[asyncio.Task] = None
        self._inactivity_timeout: float = 2.0
        self._rag: RAGStore | None = None
        self._current_block: list[str] = []
        self._recent_words: deque[str] = deque(maxlen=300)
        # Captured on start() — used by the TUI to trigger post-session processing.
        self._session_id: Optional[int] = None

    @property
    def transcript_path(self) -> str:
        """Return the filesystem path of the current session's transcript file."""
        return f"whisper-text/{self.session_logger.session_id}.txt"

    async def start(self, title: str = "") -> None:
        if self._running:
            return
        self._running = True

        await self.audio_source.start()
        await self.stt.connect()

        if self._openai_client:
            self._rag = RAGStore(
                session_id=self.session_logger.session_id,
                openai_client=self._openai_client,
            )
            import src.db.database as db
            cs = db.create_call_session(
                context=self.initial_context,
                transcript_path=f"whisper-text/{self.session_logger.session_id}.txt",
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
        logger.info("sesión guardada: whisper-text/%s.txt", self.session_logger.session_id)

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

    async def _handle_trigger(self) -> None:
        word_count = self._block_word_count()
        if word_count < self._min_substantial_words:
            logger.debug("bloque insuficiente (%d palabras < %d), esperando más", word_count, self._min_substantial_words)
            return

        block_text = " ".join(self._current_block)
        self._current_block = []

        if self._rag:
            relevant = await self._rag.search(query=block_text, top_k=5)
            rag_context = "\n".join(relevant) if relevant else block_text
        else:
            rag_context = block_text

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
            if response_mode == "silent":
                # Buffer silent-mode responses to filter meta-instructions before emitting.
                async for response in self.llm.respond(
                    base,
                    trigger_event,
                    system_prompt_addon=system_prompt_addon,
                    conservative_mode=conservative_mode,
                    response_mode=response_mode,
                    model_override=model_override,
                ):
                    if not response.is_partial:
                        full_response = response.text
                if full_response.strip().lower() not in _META_RESPONSES:
                    from src.core.interfaces import LLMResponse
                    await self.output.emit(LLMResponse(text=full_response, is_partial=False))
            else:
                async for response in self.llm.respond(
                    base,
                    trigger_event,
                    system_prompt_addon=system_prompt_addon,
                    conservative_mode=conservative_mode,
                    response_mode=response_mode,
                    model_override=model_override,
                ):
                    await self.output.emit(response)
                    if not response.is_partial:
                        full_response = response.text
        except Exception as e:
            logger.error("error calling LLM: %s", e, exc_info=True)
            from src.core.interfaces import LLMResponse
            await self.output.emit(LLMResponse(text=f"[LLM error: {e}]", is_partial=False))

        self.session_logger.log_response(rag_context, full_response)
