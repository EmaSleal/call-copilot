"""
Genera la respuesta sugerida vía Claude, en streaming. Para un copiloto
de llamadas el streaming no es opcional: ver las primeras palabras
mientras el modelo sigue generando es la diferencia entre "útil en vivo"
y "demasiado tarde para la conversación".
"""

import logging
from typing import AsyncIterator

import anthropic

from src.core.interfaces import LLMProvider, LLMResponse, TriggerEvent

logger = logging.getLogger("call_copilot.llm.claude")

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
"""


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        # Haiku acá es decisión deliberada, no de presupuesto: en este
        # pipeline la latencia importa más que el razonamiento profundo
        # que daría Sonnet/Opus para una sugerencia de 2-3 oraciones.
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def respond(
        self, context: str, trigger: TriggerEvent
    ) -> AsyncIterator[LLMResponse]:
        user_message = (
            f"Contexto de la conversación:\n{context}\n\n"
            f"Lo último relevante fue:\n{trigger.context_text}\n\n"
            "Sugerí una respuesta breve."
        )

        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=200,
                temperature=0.3,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for text in stream.text_stream:
                    yield LLMResponse(text=text, is_partial=True)

            final = await stream.get_final_message()
            full_text = "".join(
                block.text for block in final.content if hasattr(block, "text")
            )
            yield LLMResponse(text=full_text, is_partial=False)

        except anthropic.APIError as e:
            logger.error("claude API error: %s", e)
            yield LLMResponse(text=f"[error generando respuesta: {e}]", is_partial=False)
