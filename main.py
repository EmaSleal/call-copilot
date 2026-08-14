"""
Entrypoint. Arma el pipeline eligiendo implementaciones concretas según
config — acá es el ÚNICO lugar donde se decide Deepgram vs Whisper local,
WASAPI vs (futuro) tabCapture, etc. Cambiar de provider es cambiar
una línea acá, no tocar el resto del código.
"""

import asyncio
import logging
import os
import sys
from dotenv import load_dotenv
from src.core import config_defaults
from src.core.pipeline import CallCopilotPipeline
from src.audio.vad_silero import SileroVAD
from src.trigger.heuristic import HeuristicTriggerDetector
from src.output.console_output import ConsoleOutput


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("call_copilot.main")


def build_stt_provider():
    backend = config_defaults.stt_backend()  # deepgram | whisper_local

    if backend == "deepgram":
        from src.stt.deepgram_provider import DeepgramSTT
        api_key = os.getenv('DEEPGRAM_API_KEY')
        return DeepgramSTT(api_key=api_key, language="es")

    if backend == "whisper_local":
        from src.stt.whisper_local_provider import WhisperLocalSTT
        return WhisperLocalSTT(
            model_size=config_defaults.whisper_model_call(), device="cuda", language="es"
        )

    raise ValueError(f"STT_BACKEND desconocido: {backend}")


def build_llm_provider():
    backend = config_defaults.llm_backend()  # gpt | claude

    if backend == "gpt":
        from src.llm.openai_provider import OpenAIProvider
        api_key = os.getenv('OPENAI_API_KEY')
        threshold = int(os.getenv("LLM_TOKEN_THRESHOLD", "500"))
        return OpenAIProvider(api_key=api_key, token_threshold=threshold)

    if backend == "claude":
        from src.llm.claude_provider import ClaudeProvider
        api_key = os.getenv('ANTHROPIC_API_KEY')
        return ClaudeProvider(api_key=api_key)

    raise ValueError(f"LLM_BACKEND desconocido: {backend}")


async def main():
    initial_context = input("Contexto de la llamada (Enter para omitir): ").strip()

    if sys.platform == "win32":
        from src.audio.wasapi_source import WASAPILoopbackSource
        audio_source = WASAPILoopbackSource()
    else:
        from src.audio.pulse_source import PulseLoopbackSource
        audio_source = PulseLoopbackSource()
    vad = SileroVAD(silence_threshold_ms=config_defaults.silence_threshold_ms())
    stt = build_stt_provider()
    trigger = HeuristicTriggerDetector(min_words=3)
    llm = build_llm_provider()
    output = ConsoleOutput()

    from openai import AsyncOpenAI
    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

    pipeline = CallCopilotPipeline(
        audio_source=audio_source,
        vad=vad,
        stt=stt,
        trigger=trigger,
        llm=llm,
        output=output,
        llm_enabled=os.getenv("LLM_ENABLED", "true").lower() == "true",
        initial_context=initial_context,
        openai_client=openai_client,
    )

    logger.info("pipeline iniciado — Ctrl+C para detener")
    try:
        await pipeline.start()
    except KeyboardInterrupt:
        pass
    finally:
        await pipeline.stop()


if __name__ == "__main__":
    asyncio.run(main())
