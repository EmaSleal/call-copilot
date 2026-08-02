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
from src.profiles.heuristics import CONSERVATIVE_NOTE

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

_SYSTEM_PROMPT_EXPLAIN = """Sos un asistente en tiempo real. Ampliá brevemente \
el punto que se acaba de mencionar con contexto, ejemplos o información de fondo relevante.

Reglas:
- Máximo 2-3 oraciones. La persona te lee MIENTRAS habla.
- No hagas preguntas. Aportá contexto o datos útiles.
- Si el contenido ya es completo y no hay nada útil que agregar, no respondas.
- Tono neutral y profesional."""

_SYSTEM_PROMPT_SILENT = """Sos un copiloto en tiempo real. Tu ÚNICA función es \
responder cuando la audiencia hace una pregunta explícita y directa.

Reglas:
- Si el bloque es explicativo, expositivo o del presentador: NO respondas. Devolvé una respuesta vacía.
- Solo respondé si hay una pregunta clara de la audiencia dirigida al orador.
- Máximo 2-3 oraciones cuando sí respondas.
- Ante la duda, callate."""


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        # Haiku acá es decisión deliberada, no de presupuesto: en este
        # pipeline la latencia importa más que el razonamiento profundo
        # que daría Sonnet/Opus para una sugerencia de 2-3 oraciones.
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    def _build_system_prompt(
        self,
        system_prompt_addon: str,
        conservative_mode: bool,
        response_mode: str = "copilot",
    ) -> str:
        """Compose the final system prompt from base, addon, and conservative note."""
        if response_mode == "explain":
            base = _SYSTEM_PROMPT_EXPLAIN
        elif response_mode == "silent":
            base = _SYSTEM_PROMPT_SILENT
        else:
            base = _SYSTEM_PROMPT
        system = base
        if system_prompt_addon:
            system = system + "\n\n" + system_prompt_addon
        if conservative_mode and response_mode == "copilot":
            system = system + "\n\n" + CONSERVATIVE_NOTE
        return system

    async def respond(
        self,
        context: str,
        trigger: TriggerEvent,
        system_prompt_addon: str = "",
        conservative_mode: bool = False,
        response_mode: str = "copilot",
        model_override: str = "",
    ) -> AsyncIterator[LLMResponse]:
        system = self._build_system_prompt(system_prompt_addon, conservative_mode, response_mode=response_mode)

        if trigger.recent_context:
            user_message = (
                f"Transcripción reciente (en orden cronológico):\n{trigger.recent_context}\n\n"
                f"Contexto temático adicional:\n{context}\n\n"
                "Sugerí una respuesta breve."
            )
        else:
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
                system=system,
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
