"""
Contratos base del pipeline. Cada provider (audio, STT, LLM) implementa
una de estas interfaces. El pipeline orquesta sin saber qué implementación
concreta está corriendo por debajo — eso es lo que permite cambiar
Deepgram <-> Whisper local, o WASAPI <-> tabCapture, sin tocar el resto.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional


# ──────────────────────────────────────────────────────────────────────────
# Audio
# ──────────────────────────────────────────────────────────────────────────

class AudioSource(ABC):
    """Fuente de audio cruda. WASAPI loopback, micrófono, tabCapture, etc."""

    @abstractmethod
    async def start(self) -> None:
        """Inicia la captura. Debe ser idempotente si ya está activa."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Detiene la captura y libera recursos."""
        ...

    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """
        Yields chunks de audio PCM16 mono a 16kHz.
        Ese formato es el estándar que vamos a normalizar en todo el pipeline
        (es lo que Deepgram y Whisper esperan de entrada).
        """
        ...


# ──────────────────────────────────────────────────────────────────────────
# VAD (Voice Activity Detection)
# ──────────────────────────────────────────────────────────────────────────

class VADEventType(Enum):
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"        # silencio detectado tras hablar
    SILENCE = "silence"               # silencio sostenido sin habla previa


@dataclass
class VADEvent:
    type: VADEventType
    timestamp_ms: float


class VoiceActivityDetector(ABC):
    """
    Recibe chunks de audio, emite eventos de silencio/habla.
    Este es el componente que reemplaza el 'ventaneo por N oraciones'
    del proyecto anterior — acá el trigger es genuinamente el silencio,
    no un conteo arbitrario.
    """

    @abstractmethod
    def process_chunk(self, chunk: bytes) -> Optional[VADEvent]:
        """Procesa un chunk y devuelve un evento si corresponde, o None."""
        ...

    @abstractmethod
    def reset(self) -> None:
        ...


# ──────────────────────────────────────────────────────────────────────────
# STT (Speech-to-Text)
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class TranscriptSegment:
    text: str
    is_final: bool
    speaker_id: Optional[int] = None
    confidence: Optional[float] = None
    start_ms: Optional[float] = None
    end_ms: Optional[float] = None


class STTProvider(ABC):
    """
    Transcribe audio a texto en streaming.
    Implementaciones: DeepgramSTT (nube, baja latencia),
    WhisperLocalSTT (local, RTX 4060, sin costo recurrente).
    """

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        ...

    @abstractmethod
    def transcripts(self) -> AsyncIterator[TranscriptSegment]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ──────────────────────────────────────────────────────────────────────────
# Trigger / Question detection
# ──────────────────────────────────────────────────────────────────────────

class TriggerReason(Enum):
    QUESTION_DETECTED = "question_detected"
    SILENCE_TIMEOUT = "silence_timeout"
    MANUAL = "manual"


@dataclass
class TriggerEvent:
    reason: TriggerReason
    context_text: str          # el texto acumulado relevante para responder
    confidence: float = 1.0
    conservative_mode: bool = False  # True when block is discourse-marker-only and profile requires a real question
    recent_context: str = ""   # chronological rolling transcript, last ~300 words


class TriggerDetector(ABC):
    """
    Decide CUÁNDO accionar el LLM. Combina heurística rápida (regex,
    signos de interrogación) con confirmación opcional vía LLM liviano.
    Este es el componente nuevo que no existía en el repo de fact-check.
    """

    @abstractmethod
    def evaluate(
        self, new_text: str, vad_event: Optional[VADEvent]
    ) -> Optional[TriggerEvent]:
        ...


# ──────────────────────────────────────────────────────────────────────────
# LLM
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    text: str
    is_partial: bool = False   # True mientras hace streaming


class LLMProvider(ABC):
    """
    Genera la respuesta sugerida. Implementaciones: ClaudeProvider, GPTProvider.
    Streaming es obligatorio acá — en una llamada en vivo, esperar la
    respuesta completa antes de mostrar nada mata el propósito.

    Optional convention (not enforced by this ABC): implementations SHOULD
    expose a `provider_id: str` class attribute (e.g. "claude", "gpt")
    identifying the active backend. The pipeline reads it defensively via
    `getattr(self.llm, "provider_id", None)` to validate a profile's model
    override offline, without assuming every LLMProvider defines it.
    """

    @abstractmethod
    def respond(
        self,
        context: str,
        trigger: TriggerEvent,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ) -> AsyncIterator[LLMResponse]:
        ...


# ──────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────

class OutputSink(ABC):
    """
    Dónde aparece la respuesta. Overlay, consola, TTS — todavía sin definir,
    por eso queda como interfaz mínima desde ya.
    """

    @abstractmethod
    async def emit(self, response: LLMResponse) -> None:
        ...
