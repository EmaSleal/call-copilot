"""
VAD basado en Silero. Corre local, ~1ms por chunk en CPU (ni hace falta GPU).
Es el componente que el repo de fact-check no tenía: ahí el 'trigger' era
contar N oraciones, acá es silencio real medido en el audio.
"""

import logging
import time
from typing import Optional

import numpy as np
import torch

from src.core.interfaces import VoiceActivityDetector, VADEvent, VADEventType

logger = logging.getLogger("call_copilot.vad")


class SileroVAD(VoiceActivityDetector):
    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold_ms: int = 700,
        speech_threshold: float = 0.5,
    ):
        """
        silence_threshold_ms: cuánto silencio sostenido antes de emitir
            SPEECH_END. 700ms es buen punto de partida para llamadas —
            suficiente para no cortar pausas naturales de respiración,
            corto para sentirse responsive.
        speech_threshold: confianza mínima del modelo para considerar
            que hay voz en el chunk (0.0-1.0).
        """
        self.sample_rate = sample_rate
        self.silence_threshold_ms = silence_threshold_ms
        self.speech_threshold = speech_threshold

        self.model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        self.model.eval()

        self._is_speaking = False
        self._last_speech_ts: Optional[float] = None
        self._silence_event_emitted = False

        # silero espera chunks de tamaño fijo (512 samples @ 16kHz)
        self._chunk_size = 512
        self._buffer = np.array([], dtype=np.float32)

    def process_chunk(self, chunk: bytes) -> Optional[VADEvent]:
        # chunk viene como PCM16 bytes -> normalizar a float32 [-1, 1]
        int16 = np.frombuffer(chunk, dtype=np.int16)
        float32 = int16.astype(np.float32) / 32768.0

        self._buffer = np.concatenate([self._buffer, float32])

        event: Optional[VADEvent] = None

        while len(self._buffer) >= self._chunk_size:
            piece = self._buffer[: self._chunk_size]
            self._buffer = self._buffer[self._chunk_size :]

            with torch.no_grad():
                prob = self.model(torch.from_numpy(piece), self.sample_rate).item()

            now = time.time() * 1000  # ms

            if prob >= self.speech_threshold:
                if not self._is_speaking:
                    self._is_speaking = True
                    self._silence_event_emitted = False
                    event = VADEvent(type=VADEventType.SPEECH_START, timestamp_ms=now)
                    logger.debug("speech start")
                self._last_speech_ts = now
            else:
                if self._is_speaking and self._last_speech_ts is not None:
                    silence_elapsed = now - self._last_speech_ts
                    if silence_elapsed >= self.silence_threshold_ms and not self._silence_event_emitted:
                        self._is_speaking = False
                        self._silence_event_emitted = True
                        event = VADEvent(type=VADEventType.SPEECH_END, timestamp_ms=now)
                        logger.debug("speech end (silence %.0fms)", silence_elapsed)

        return event

    def reset(self) -> None:
        self._is_speaking = False
        self._last_speech_ts = None
        self._silence_event_emitted = False
        self._buffer = np.array([], dtype=np.float32)
        if hasattr(self.model, "reset_states"):
            self.model.reset_states()
