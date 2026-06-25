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

logger = logging.getLogger("call_copilot.pipeline")


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
        min_trigger_words: int = 15,
        mid_trigger_words: int = 40,
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
        self._min_trigger_words = min_trigger_words
        self._mid_trigger_words = mid_trigger_words

        self._running = False
        self._segments: deque[str] = deque(maxlen=10)
        self._inactivity_task: Optional[asyncio.Task] = None
        self._inactivity_timeout: float = 2.0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        await self.audio_source.start()
        await self.stt.connect()

        # tres tareas concurrentes: alimentar STT con audio,
        # consumir transcripciones, y nada más por ahora —
        # el trigger se evalúa inline al consumir transcripts.
        await asyncio.gather(
            self._feed_audio_to_stt(),
            self._consume_transcripts(),
            self._periodic_snapshot(),
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

    async def _periodic_snapshot(self, interval: int = 20) -> None:
        while self._running:
            await asyncio.sleep(interval)
            context = self._clean_context()
            if context:
                self.session_logger.log_snapshot(context)

    async def _consume_transcripts(self) -> None:
        async for segment in self.stt.transcripts():
            await self._handle_segment(segment)

    def _clean_context(self) -> str:
        text = " ".join(self._segments)
        # Si hay una pregunta abierta, enfocarse solo desde la última
        idx = text.rfind("¿")
        if idx != -1:
            text = text[idx:]
        tokens = text.split()
        if not tokens:
            return ""
        deduped = [tokens[0]]
        for tok in tokens[1:]:
            if tok.lower() != deduped[-1].lower():
                deduped.append(tok)
        return " ".join(deduped)

    async def _inactivity_trigger(self, delay: float | None = None) -> None:
        try:
            await asyncio.sleep(
                delay if delay is not None else self._inactivity_timeout
            )
            await self._handle_trigger(TriggerEvent(
                reason=TriggerReason.SILENCE_TIMEOUT,
                context_text="",
                confidence=0.8 if (delay is not None and delay < self._inactivity_timeout) else 0.6,
            ))
        except asyncio.CancelledError:
            pass

    async def _handle_segment(self, segment: TranscriptSegment) -> None:
        if not segment.is_final:
            return

        if self.on_segment:
            self.on_segment(segment)

        self._segments.append(segment.text)
        self.session_logger.log_transcript(segment.text)

        if self._inactivity_task:
            self._inactivity_task.cancel()

        delay = self._content_trigger_delay(segment.text)
        self._inactivity_task = asyncio.create_task(self._inactivity_trigger(delay))

    def _content_trigger_delay(self, last_segment_text: str) -> float:
        """
        Returns 0 to fire the LLM immediately (content boundary detected),
        or self._inactivity_timeout to wait for silence as usual.

        Mirrors the video pipeline logic: scan the full accumulated context
        for the last sentence/clause boundary past the word-count threshold.
        """
        context = " ".join(self._segments)
        words = context.split()
        word_count = len(words)

        last_char = last_segment_text.rstrip()[-1:] if last_segment_text.strip() else ""

        # Clean sentence end with enough content → fire immediately
        if word_count >= self._min_trigger_words and last_char in _SENTENCE_END:
            return 0.0

        # Clause boundary with more content → fire with a short delay so
        # the speaker can continue if it was just a mid-sentence comma
        if word_count >= self._mid_trigger_words and last_char in _CLAUSE_END:
            return 0.5

        # Scan full context for the last sentence boundary past min threshold
        if word_count >= self._min_trigger_words:
            for i in range(len(words) - 2, self._min_trigger_words - 1, -1):
                lc = words[i][-1:] if words[i] else ""
                if lc in _SENTENCE_END:
                    return 0.0
                if lc in _CLAUSE_END and word_count >= self._mid_trigger_words:
                    return 0.5

        return self._inactivity_timeout

    async def _handle_trigger(self, trigger_event) -> None:
        context = self._clean_context()
        if not context:
            return

        print(f"\n[contexto] {context}\n")

        if not self.llm_enabled:
            print("─" * 40)
            self._segments.clear()
            return

        base = f"{self.initial_context}\n\n{context}".strip() if self.initial_context else context
        full_context = f"{base}\n\n(Transcripción completa en whisper-text/{self.session_logger.session_id}.txt se filtra por linea por hora ej: [21:29:18])"
        full_response = ""
        try:
            async for response in self.llm.respond(full_context, trigger_event):
                await self.output.emit(response)
                if not response.is_partial:
                    full_response = response.text
        except Exception as e:
            logger.error("error calling LLM: %s", e, exc_info=True)
            from src.core.interfaces import LLMResponse
            await self.output.emit(LLMResponse(text=f"[LLM error: {e}]", is_partial=False))

        self.session_logger.log_response(context, full_response)
        self._segments.clear()
