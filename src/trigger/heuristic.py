"""
Decide cuándo accionar el LLM. Empieza con heurística pura (regex,
sin llamadas extra) porque en una llamada en vivo cada milisegundo de
latencia se nota. La confirmación vía LLM queda como capa opcional
para cuando se valide que la heurística sola da demasiados falsos
positivos/negativos.
"""

import re
from typing import Optional

from src.core.interfaces import TriggerDetector, TriggerEvent, TriggerReason, VADEvent, VADEventType


# Palabras interrogativas en español e inglés — cubre el caso "agnóstico
# de plataforma" donde la llamada puede ser en cualquiera de los dos.
_QUESTION_WORDS = re.compile(
    r"\b("
    r"qué|que|cómo|como|cuándo|cuando|dónde|donde|por qué|porque|"
    r"cuál|cual|quién|quien|cuánto|cuanto|"
    r"what|how|when|where|why|which|who|whose|"
    r"could you|can you|would you|do you|does|did you|"
    r"podrías|podes|puedes|sabes|tienes|hay"
    r")\b",
    re.IGNORECASE,
)

_QUESTION_MARK = re.compile(r"\?")


class HeuristicTriggerDetector(TriggerDetector):
    def __init__(self, min_words: int = 3):
        """
        min_words: ignora fragmentos demasiado cortos para ser una
        pregunta real (evita falsos positivos en transcripciones parciales).
        """
        self.min_words = min_words
        self._pending_text = ""

    def evaluate(
        self, new_text: str, vad_event: Optional[VADEvent]
    ) -> Optional[TriggerEvent]:
        if new_text:
            self._pending_text = (self._pending_text + " " + new_text).strip()

        # Dispara solo cuando el VAD confirma silencio sostenido.
        # La detección de pregunta sube la confianza pero no adelanta el disparo.
        if vad_event and vad_event.type == VADEventType.SPEECH_END:
            if self._pending_text and len(self._pending_text.split()) >= self.min_words:
                text = self._pending_text
                is_question = self._looks_like_question(text)
                self._pending_text = ""
                return TriggerEvent(
                    reason=TriggerReason.QUESTION_DETECTED if is_question else TriggerReason.SILENCE_TIMEOUT,
                    context_text=text,
                    confidence=0.9 if is_question else 0.6,
                )

        return None

    def _looks_like_question(self, text: str) -> bool:
        if not text or len(text.split()) < self.min_words:
            return False
        return bool(_QUESTION_MARK.search(text) or _QUESTION_WORDS.search(text))
