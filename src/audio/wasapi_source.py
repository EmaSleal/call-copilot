"""
Captura el audio de salida del sistema en Windows vía WASAPI loopback.
Retoma el approach validado al inicio de la conversación (PyAudioWPatch),
ahora detrás de la interfaz AudioSource para que sea intercambiable con
una futura implementación de tabCapture del lado browser.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    # Non-Windows dev/test environments: PyAudioWPatch is a win32-only
    # dependency (pyproject.toml). list_output_devices() below degrades to
    # [] here, same contract as pulse_source.list_sinks() on non-Linux.
    # WASAPILoopbackSource itself is only ever instantiated behind a
    # `sys.platform == "win32"` guard (src/tui/tabs/call.py), so it never
    # actually needs `pyaudio` to be real on this branch.
    pyaudio = None

from src.core.interfaces import AudioSource

logger = logging.getLogger("call_copilot.audio.wasapi")


@dataclass
class DeviceInfo:
    index: int
    name: str


def device_label(device: DeviceInfo) -> str:
    """Human-readable Select option label for a WASAPI loopback device."""
    return device.name


def list_output_devices() -> list[DeviceInfo]:
    """
    List WASAPI loopback-capable output devices (what you'd hear through
    speakers/headphones), so the user can pick which one to capture —
    mirrors src.audio.pulse_source.list_sinks() on Linux. Returns [] when
    pyaudiowpatch isn't available (non-Windows) or WASAPI can't be
    queried; callers should fall back to the "default device" behavior
    in that case.
    """
    if pyaudio is None:
        return []

    pa = pyaudio.PyAudio()
    try:
        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return []
        return [
            DeviceInfo(index=dev["index"], name=dev["name"])
            for i in range(pa.get_device_count())
            for dev in [pa.get_device_info_by_index(i)]
            if dev["hostApi"] == wasapi_info["index"] and dev.get("isLoopbackDevice", False)
        ]
    finally:
        pa.terminate()


class WASAPILoopbackSource(AudioSource):
    def __init__(
        self,
        target_sample_rate: int = 16000,
        chunk: int = 1024,
        device_index: Optional[int] = None,
    ):
        """
        device_index: index from list_output_devices()/DeviceInfo.index.
        None (default) auto-detects the loopback device matching the
        system's current default output, same as before this option
        existed.
        """
        self.target_sample_rate = target_sample_rate
        self.chunk = chunk
        self.device_index = device_index

        self._pa = None
        self._stream = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        if self._running:
            return

        self._pa = pyaudio.PyAudio()

        if self.device_index is not None:
            loopback_device = self._pa.get_device_info_by_index(self.device_index)
        else:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self._pa.get_device_info_by_index(
                wasapi_info["defaultOutputDevice"]
            )

            loopback_device = None
            for i in range(self._pa.get_device_count()):
                dev = self._pa.get_device_info_by_index(i)
                if (
                    default_speakers["name"] in dev["name"]
                    and dev["hostApi"] == wasapi_info["index"]
                    and dev.get("isLoopbackDevice", False)
                ):
                    loopback_device = dev
                    break

        if loopback_device is None:
            raise RuntimeError(
                "No se encontró dispositivo loopback para el output activo. "
                "Verificá que PyAudioWPatch esté instalado correctamente."
            )

        native_rate = int(loopback_device["defaultSampleRate"])
        self._native_rate = native_rate
        self._channels = loopback_device["maxInputChannels"]

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=native_rate,
            input=True,
            input_device_index=loopback_device["index"],
            frames_per_buffer=self.chunk,
            stream_callback=self._callback,
        )
        self._loop = asyncio.get_event_loop()
        self._running = True
        self._stream.start_stream()
        logger.info(
            "WASAPI loopback iniciado (device=%s, rate=%d, channels=%d)",
            loopback_device["name"], native_rate, self._channels,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        # se llama desde el thread de PortAudio -> hay que pasar al loop
        # asyncio de forma thread-safe
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, in_data)
        except RuntimeError:
            pass  # loop ya cerrado, ignorar últimos callbacks en shutdown
        return (None, pyaudio.paContinue)

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa:
            self._pa.terminate()
            self._pa = None
        logger.info("WASAPI loopback detenido")

    def _normalize_chunk(self, raw: bytes) -> bytes:
        samples = np.frombuffer(raw, dtype=np.int16)

        if self._channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1).astype(np.int16)

        # 48000 / 16000 = 3 exactly — simple decimation is lossless for speech
        factor = self._native_rate // self.target_sample_rate
        if factor > 1:
            samples = samples[::factor]

        return samples.tobytes()

    async def stream(self) -> AsyncIterator[bytes]:
        while self._running:
            chunk = await self._queue.get()
            yield self._normalize_chunk(chunk)
