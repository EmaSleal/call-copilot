"""
Output mínimo por consola. Placeholder a propósito: todavía no definiste
si la salida final es overlay, ventana separada, o TTS — esto solo
sirve para validar el pipeline end-to-end mientras se decide.
"""

import sys

from src.core.interfaces import OutputSink, LLMResponse


class ConsoleOutput(OutputSink):
    async def emit(self, response: LLMResponse) -> None:
        if response.is_partial:
            sys.stdout.write(response.text)
            sys.stdout.flush()
        else:
            sys.stdout.write("\n" + "─" * 40 + "\n")
            sys.stdout.flush()
