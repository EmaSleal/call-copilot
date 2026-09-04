"""
STT vía faster-whisper, corriendo local en la RTX 4060.
No es streaming nativo como Deepgram (Whisper procesa por ventanas),
así que acá el 'streaming' se simula procesando buffers cortos
acumulados — hay un trade-off de latencia real frente a Deepgram,
documentado en _send_audio.
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

import numpy as np
from faster_whisper import WhisperModel

from src.core.interfaces import STTProvider, TranscriptSegment

logger = logging.getLogger("call_copilot.stt.whisper_local")


class WhisperLocalSTT(STTProvider):
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cuda",
        compute_type: str = "float16",
        language: str = "es",
        buffer_seconds: float = 5.0,
        sample_rate: int = 16000,
    ):
        """
        buffer_seconds: cada cuánto se dispara una transcripción.
        Más bajo = más responsive pero más overhead de GPU por chunk
        más corto (peor relación señal/contexto para el modelo).
        2s es el punto medio razonable para un copiloto de llamadas.
        """
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.language = language
        self.sample_rate = sample_rate
        self.buffer_seconds = buffer_seconds
        self._buffer_size = int(sample_rate * buffer_seconds)

        self._audio_buffer = np.array([], dtype=np.float32)
        self._transcript_queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        # no hay conexión real que abrir — el modelo ya está cargado en __init__
        logger.info("whisper local listo (modelo cargado)")

    async def send_audio(self, chunk: bytes) -> None:
        int16 = np.frombuffer(chunk, dtype=np.int16)
        float32 = int16.astype(np.float32) / 32768.0

        async with self._lock:
            self._audio_buffer = np.concatenate([self._audio_buffer, float32])

            if len(self._audio_buffer) >= self._buffer_size:
                to_process = self._audio_buffer
                self._audio_buffer = np.array([], dtype=np.float32)
                asyncio.create_task(self._transcribe(to_process))

    async def _transcribe(self, audio: np.ndarray) -> None:
        # faster-whisper es sync/bloqueante -> correrlo en thread pool
        # para no congelar el event loop mientras procesa en GPU.
        #
        # send_audio() lanza esto como fire-and-forget (asyncio.create_task,
        # nunca awaited) — sin este try/except, cualquier excepción acá
        # (ej. una librería CUDA faltante) desaparece silenciosamente como
        # "Task exception was never retrieved" recién cuando el garbage
        # collector junta la task, sin avisarle nada al usuario ni dejar un
        # traceback inmediato y legible en el log.
        try:
            loop = asyncio.get_event_loop()
            segments, _ = await loop.run_in_executor(
                None,
                lambda: self.model.transcribe(
                    audio,
                    language=self.language,
                    beam_size=1,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=300),
                ),
            )
            for seg in segments:
                await self._transcript_queue.put(
                    TranscriptSegment(text=seg.text.strip(), is_final=True)
                )
        except Exception:
            logger.exception("whisper local transcription failed")

    def transcripts(self) -> AsyncIterator[TranscriptSegment]:
        return self._iter_queue()

    async def _iter_queue(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            segment = await self._transcript_queue.get()
            yield segment

    async def close(self) -> None:
        pass  # nada que cerrar — el modelo se libera con garbage collection
