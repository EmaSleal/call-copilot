"""
Genera la respuesta sugerida vía OpenAI, en streaming.

Elige entre dos modelos según el tamaño del contexto de entrada:
  - nano  → contextos cortos (debajo del umbral de tokens)
  - mini  → contextos más largos (igual o por encima del umbral)

El umbral se configura vía LLM_TOKEN_THRESHOLD (default: 500).
La estimación de tokens usa la heurística ~4 chars/token — suficientemente
precisa para elegir el tier sin necesidad de una dependencia extra (tiktoken).
"""

import logging
from typing import AsyncIterator

import openai

from src.core.interfaces import LLMProvider, LLMResponse, TriggerEvent

logger = logging.getLogger("call_copilot.llm.openai")

_NANO_MODEL = "gpt-5.4-nano"
_MINI_MODEL = "gpt-5.4-mini"
_DEFAULT_TOKEN_THRESHOLD = 500

_SYSTEM_PROMPT = """Sos un copiloto de llamadas en tiempo real. Tu trabajo es \
sugerir una respuesta breve y directa a lo que se acaba de preguntar o decir \
en la conversación.

Reglas:
- Máximo 2-3 oraciones. La persona te está leyendo MIENTRAS habla, no tiene \
tiempo de leer un párrafo largo.
- Andá directo al punto, sin preámbulo ("Podrías decir...", "Una opción es...").
- Si el contexto es ambiguo o falta información, sugerí la pregunta de \
clarificación más útil, no inventes una respuesta.
- Tono neutral y profesional salvo que el contexto de la conversación indique \
otra cosa.
- Del texto recibido, ignorá lo que no sea relevante para la pregunta o el \
momento de la conversación.
"""


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        token_threshold: int = _DEFAULT_TOKEN_THRESHOLD,
        nano_model: str = _NANO_MODEL,
        mini_model: str = _MINI_MODEL,
    ):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.token_threshold = token_threshold
        self.nano_model = nano_model
        self.mini_model = mini_model

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _select_model(self, context: str, trigger_text: str) -> str:
        tokens = self._estimate_tokens(context + trigger_text)
        return self.mini_model if tokens >= self.token_threshold else self.nano_model

    async def respond(
        self, context: str, trigger: TriggerEvent
    ) -> AsyncIterator[LLMResponse]:
        model = self._select_model(context, trigger.context_text)
        logger.debug("modelo seleccionado: %s", model)

        user_message = (
            f"Contexto de la conversación:\n{context}\n\n"
            f"Lo último relevante fue:\n{trigger.context_text}\n\n"
            "Sugerí una respuesta breve."
        )

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                max_completion_tokens=200,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                stream=True,
            )

            full_text = ""
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    yield LLMResponse(text=delta.content, is_partial=True)

            yield LLMResponse(text=full_text, is_partial=False)

        except openai.APIError as e:
            logger.error("openai API error: %s", e)
            yield LLMResponse(text=f"[error generando respuesta: {e}]", is_partial=False)
