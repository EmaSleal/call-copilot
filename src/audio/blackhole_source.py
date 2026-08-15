"""
Captura el audio de salida del sistema en macOS vía BlackHole, un driver de
audio virtual (brew install blackhole-2ch) que aparece como un input device
más — sin ScreenCaptureKit ni bridging a Swift/ObjC de por medio. El usuario
debe instalarlo y enrutar la salida del sistema hacia él (directamente o vía
un Multi-Output Device) antes de iniciar una llamada.

PyAudio se importa perezosamente en start(), no a nivel de módulo, así este
archivo (y sus helpers puros de abajo) sigue siendo importable/testeable en
plataformas sin PyAudio instalado — Linux CI, por ejemplo.
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

import numpy as np

from src.core.interfaces import AudioSource

logger = logging.getLogger("call_copilot.audio.blackhole")


def _find_blackhole_device(pa) -> Optional[dict]:
    """
    Escanea los input devices de `pa` buscando BlackHole por nombre
    (case-insensitive, cubre "BlackHole 2ch", "BlackHole 16ch", etc).
    Devuelve el device info dict, o None si no está instalado.
    """
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        if "blackhole" in dev["name"].lower() and dev["maxInputChannels"] > 0:
            return dev
    return None


def _normalize_chunk(raw: bytes, channels: int, native_rate: int, target_rate: int) -> bytes:
    samples = np.frombuffer(raw, dtype=np.int16)

    if channels == 2:
        samples = samples.reshape(-1, 2).mean(axis=1).astype(np.int16)

    factor = native_rate // target_rate
    if factor > 1:
        samples = samples[::factor]

    return samples.tobytes()


class BlackHoleLoopbackSource(AudioSource):
    def __init__(self, target_sample_rate: int = 16000, chunk: int = 1024):
        self.target_sample_rate = target_sample_rate
        self.chunk = chunk

        self._pa = None
        self._pyaudio_module = None
        self._stream = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False
        self._native_rate = target_sample_rate
        self._channels = 1

    async def start(self) -> None:
        if self._running:
            return

        import pyaudio

        self._pyaudio_module = pyaudio
        self._pa = pyaudio.PyAudio()

        device = _find_blackhole_device(self._pa)
        if device is None:
            raise RuntimeError(
                "No se encontró el dispositivo BlackHole. Instalalo con "
                "'brew install blackhole-2ch', configuralo como salida de "
                "audio del sistema (o como parte de un Multi-Output Device) "
                "y volvé a intentar."
            )

        self._native_rate = int(device["defaultSampleRate"])
        self._channels = device["maxInputChannels"]

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._native_rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=self.chunk,
            stream_callback=self._callback,
        )
        self._loop = asyncio.get_event_loop()
        self._running = True
        self._stream.start_stream()
        logger.info(
            "BlackHole loopback iniciado (device=%s, rate=%d, channels=%d)",
            device["name"], self._native_rate, self._channels,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        # se llama desde el thread de PortAudio -> hay que pasar al loop
        # asyncio de forma thread-safe
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, in_data)
        except RuntimeError:
            pass  # loop ya cerrado, ignorar últimos callbacks en shutdown
        return (None, self._pyaudio_module.paContinue)

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        logger.info("BlackHole loopback detenido")

    async def stream(self) -> AsyncIterator[bytes]:
        while self._running:
            chunk = await self._queue.get()
            yield _normalize_chunk(chunk, self._channels, self._native_rate, self.target_sample_rate)
