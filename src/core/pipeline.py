"""
Orquesta el flujo completo: audio -> VAD -> STT -> trigger -> LLM -> output.
No conoce implementaciones concretas, solo las interfaces de core.interfaces.
Esto es lo que permite que WASAPI/tabCapture, Deepgram/Whisper,
Claude/GPT sean intercambiables vía config sin tocar esta clase.
"""

import asyncio
import logging
from collections import deque
from typing import Optional

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

    async def _inactivity_trigger(self) -> None:
        try:
            await asyncio.sleep(self._inactivity_timeout)
            await self._handle_trigger(TriggerEvent(
                reason=TriggerReason.SILENCE_TIMEOUT,
                context_text="",
                confidence=0.6,
            ))
        except asyncio.CancelledError:
            pass

    async def _handle_segment(self, segment: TranscriptSegment) -> None:
        if not segment.is_final:
            return

        self._segments.append(segment.text)
        self.session_logger.log_transcript(segment.text)

        if self._inactivity_task:
            self._inactivity_task.cancel()
        self._inactivity_task = asyncio.create_task(self._inactivity_trigger())

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
        async for response in self.llm.respond(full_context, trigger_event):
            await self.output.emit(response)
            if not response.is_partial:
                full_response = response.text

        self.session_logger.log_response(context, full_response)
        self._segments.clear()
