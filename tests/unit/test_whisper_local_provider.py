"""
Unit tests for src/stt/whisper_local_provider.py::_transcribe().

_transcribe() runs as a fire-and-forget asyncio task from send_audio()
(asyncio.create_task, never awaited) — before this fix, any exception
raised inside it (e.g. a missing CUDA library) vanished silently, only
surfacing as "Task exception was never retrieved" once the garbage
collector happened to reap the task, with no immediate, discoverable log
entry and nothing shown to the user.
"""

import asyncio
from unittest.mock import MagicMock

import numpy as np

from src.stt.whisper_local_provider import WhisperLocalSTT


def _make_provider(monkeypatch) -> WhisperLocalSTT:
    monkeypatch.setattr("src.stt.whisper_local_provider.WhisperModel", MagicMock())
    return WhisperLocalSTT(model_size="tiny", device="cpu")


class TestTranscribeErrorHandling:
    def test_exception_is_caught_logged_and_not_raised(self, monkeypatch, caplog):
        provider = _make_provider(monkeypatch)
        provider.model.transcribe.side_effect = RuntimeError(
            "Library libcublas.so.12 is not found or cannot be loaded"
        )

        with caplog.at_level("ERROR", logger="call_copilot.stt.whisper_local"):
            asyncio.run(provider._transcribe(np.zeros(100, dtype=np.float32)))

        assert "whisper local transcription failed" in caplog.text
        assert provider._transcript_queue.empty()


class TestTranscribeSuccess:
    def test_queues_a_transcript_segment_per_result(self, monkeypatch):
        provider = _make_provider(monkeypatch)
        fake_segment = MagicMock(text="  hola mundo  ")
        provider.model.transcribe.return_value = ([fake_segment], None)

        asyncio.run(provider._transcribe(np.zeros(100, dtype=np.float32)))

        result = provider._transcript_queue.get_nowait()
        assert result.text == "hola mundo"
        assert result.is_final is True
