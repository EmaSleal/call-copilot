"""
Linux loopback audio capture using parec (PulseAudio/PipeWire CLI).

Spawns parec pointed at the default sink monitor, reads raw PCM s16le
at 16kHz mono, and yields chunks into the pipeline queue.
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from src.core.interfaces import AudioSource

logger = logging.getLogger("call_copilot.audio.pulse")

TARGET_RATE = 16000
CHANNELS = 1
CHUNK_BYTES = 4096  # ~128ms at 16kHz mono s16le


def _default_monitor() -> str:
    try:
        sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        return f"{sink}.monitor"
    except Exception as e:
        raise RuntimeError(f"Cannot determine default sink via pactl: {e}")


@dataclass
class SinkInfo:
    name: str
    state: str


def _parse_sinks(raw: str) -> list[SinkInfo]:
    """
    Parse `pactl list short sinks` tab-separated output (id, name, driver,
    format, state) into SinkInfo rows. Malformed/blank lines are skipped.
    """
    sinks = []
    for line in raw.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        _id, name, _driver, _format, state = parts[:5]
        sinks.append(SinkInfo(name=name, state=state))
    return sinks


def sink_label(sink: SinkInfo) -> str:
    """
    Human-readable Select option label. Includes `state` (RUNNING/SUSPENDED/
    IDLE) so the user can spot which sink is actually carrying audio right
    now — the "default sink" pactl reports can silently diverge from that
    (e.g. suspended headset set as default while a different device plays
    the call), which is exactly the failure this selector exists to avoid.
    """
    short = sink.name.removeprefix("alsa_output.")
    return f"{short} — {sink.state}"


def list_sinks() -> list[SinkInfo]:
    """
    List available PulseAudio/PipeWire sinks via `pactl`. Returns [] when
    pactl isn't available (non-Linux, not installed) or the call fails —
    callers should fall back to the "default sink" behavior in that case.
    """
    try:
        raw = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return _parse_sinks(raw)


class PulseLoopbackSource(AudioSource):
    def __init__(self, chunk_bytes: int = CHUNK_BYTES, device: Optional[str] = None):
        """
        device: sink name (as returned by list_sinks()/SinkInfo.name),
        without the ".monitor" suffix. None (default) falls back to
        capturing the system's default sink, same as before this option
        existed.
        """
        self.chunk_bytes = chunk_bytes
        self.device = device
        self._proc: Optional[subprocess.Popen] = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._running = False
        self._reader_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return

        monitor = f"{self.device}.monitor" if self.device else _default_monitor()
        self._proc = subprocess.Popen(
            [
                "parec",
                f"--device={monitor}",
                f"--rate={TARGET_RATE}",
                f"--channels={CHANNELS}",
                "--format=s16le",
                "--latency-msec=50",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._running = True
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("parec loopback started (monitor=%s, rate=%d)", monitor, TARGET_RATE)

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running and self._proc and self._proc.poll() is None:
            data = await loop.run_in_executor(None, self._proc.stdout.read, self.chunk_bytes)
            if data:
                await self._queue.put(data)

    async def stop(self) -> None:
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc:
            self._proc.terminate()
            self._proc = None
        logger.info("parec loopback stopped")

    async def stream(self) -> AsyncIterator[bytes]:
        while self._running:
            chunk = await self._queue.get()
            yield chunk
