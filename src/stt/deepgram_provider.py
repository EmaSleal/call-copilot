"""
STT vía Deepgram. Mismo approach que validamos en la auditoría del
repo de fact-check, pero ahora detrás de la interfaz STTProvider
para que sea intercambiable con Whisper local.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import websockets

from src.core.interfaces import STTProvider, TranscriptSegment

logger = logging.getLogger("call_copilot.stt.deepgram")

_KEEPALIVE_INTERVAL_S = 10


class DeepgramSTT(STTProvider):
    def __init__(self, api_key: str, sample_rate: int = 16000, language: str = "es"):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.language = language
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._transcript_queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()
        self._listen_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        params = "&".join([
            "encoding=linear16",
            f"sample_rate={self.sample_rate}",
            "channels=1",
            "model=nova-3",
            f"language={self.language}",
            "punctuate=true",
            "interim_results=true",
            "utterance_end_ms=1000",
            "smart_format=true",
            "vad_events=true",
        ])
        url = f"wss://api.deepgram.com/v1/listen?{params}"

        self._ws = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Token {self.api_key}"},
            ping_interval=None,  # Deepgram manages its own keepalive
        )
        self._listen_task = asyncio.create_task(self._listen())
        self._keepalive_task = asyncio.create_task(self._keepalive())
        logger.info("deepgram connected (lang=%s, model=nova-3)", self.language)

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is None:
            raise RuntimeError("DeepgramSTT.connect() must be called before send_audio()")
        await self._ws.send(chunk)

    def transcripts(self) -> AsyncIterator[TranscriptSegment]:
        return self._iter_queue()

    async def _iter_queue(self) -> AsyncIterator[TranscriptSegment]:
        while True:
            segment = await self._transcript_queue.get()
            yield segment

    async def _keepalive(self) -> None:
        try:
            while True:
                await asyncio.sleep(_KEEPALIVE_INTERVAL_S)
                if self._ws is not None:
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            pass

    async def _listen(self) -> None:
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                if data.get("type") == "UtteranceEnd":
                    continue

                alt = data.get("channel", {}).get("alternatives", [{}])[0]
                text = alt.get("transcript", "").strip()
                if not text:
                    continue

                segment = TranscriptSegment(
                    text=text,
                    is_final=data.get("is_final", False),
                    speaker_id=(alt.get("words") or [{}])[0].get("speaker"),
                    confidence=alt.get("confidence"),
                )
                await self._transcript_queue.put(segment)
        except websockets.ConnectionClosed as e:
            logger.warning("deepgram connection closed: %s", e)

    async def close(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._listen_task:
            self._listen_task.cancel()
        if self._ws:
            await self._ws.close()
            self._ws = None
