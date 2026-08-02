"""
Provider construction from config, and heavy-model preloading before
Textual mounts. Shared by app.py's entrypoint (main() -> _preload_models())
and CallCopilotTab (_build_stt/_build_llm per call, plus reading the
_silero_vad_instance singleton _preload_models fills in) — kept out of both
to avoid a call.py <-> app.py import cycle.

tqdm + Python 3.14 + Textual's open file descriptors conflict when
multiprocessing tries to fork a resource tracker. torch.hub.load also
blocks. Running everything in _preload_models() before Textual opens the
terminal avoids freezing the Textual event loop.
"""

import os

from src.core import config_defaults

_whisper_stt_instance = None
_silero_vad_instance = None


def _build_stt():
    backend = config_defaults.stt_backend()
    if backend == "deepgram":
        from src.stt.deepgram_provider import DeepgramSTT

        return DeepgramSTT(api_key=os.getenv("DEEPGRAM_API_KEY"), language="es")
    if _whisper_stt_instance is not None:
        return _whisper_stt_instance
    from src.stt.whisper_local_provider import WhisperLocalSTT

    model_size = config_defaults.whisper_model_call()
    return WhisperLocalSTT(model_size=model_size, device="cuda", language="es")


def _build_llm():
    backend = config_defaults.llm_backend()
    if backend == "gpt":
        from src.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=os.getenv("OPENAI_API_KEY"),
            token_threshold=int(os.getenv("LLM_TOKEN_THRESHOLD", "500")),
        )
    # "gpt" is now the canonical realtime default (config_defaults.DEFAULT_LLM_BACKEND);
    # "claude" only applies when explicitly configured. "ollama" is not supported
    # for the copilot LLM (Ollama is used in the video classifier, not real-time streaming).
    from src.llm.claude_provider import ClaudeProvider

    return ClaudeProvider(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _preload_models() -> None:
    """Load all heavy models before Textual opens the terminal."""
    global _whisper_stt_instance, _silero_vad_instance

    backend = config_defaults.stt_backend()
    if backend == "whisper_local":
        from src.stt.whisper_local_provider import WhisperLocalSTT

        model_size = config_defaults.whisper_model_call()
        print(f"Loading Whisper model '{model_size}'...")
        _whisper_stt_instance = WhisperLocalSTT(
            model_size=model_size, device="cuda", language="es"
        )
        print("Whisper ready.")

    print("Loading Silero VAD...")
    from src.audio.vad_silero import SileroVAD

    _silero_vad_instance = SileroVAD(silence_threshold_ms=2000)
    print("VAD ready.")
