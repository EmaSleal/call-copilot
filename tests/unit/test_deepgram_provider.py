"""
Unit tests for DeepgramSTT.close() — verifies the graceful-shutdown fixes
made after auditing the implementation against Deepgram's official
streaming docs: sending CloseStream before disconnecting (so buffered
final results aren't dropped) and a keepalive interval inside Deepgram's
recommended 3-5s window (their timeout fires at 10s).
"""

import asyncio
import json

import pytest

from src.stt.deepgram_provider import DeepgramSTT, _KEEPALIVE_INTERVAL_S


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def stt():
    return DeepgramSTT(api_key="fake-key")


class TestKeepaliveInterval:
    def test_interval_within_deepgram_recommended_window(self):
        """Deepgram closes the socket (NET-0001) after 10s of silence and
        recommends sending KeepAlive every 3-5s."""
        assert 3 <= _KEEPALIVE_INTERVAL_S <= 5


class TestClose:
    def test_sends_close_stream_before_closing_socket(self, stt):
        ws = _FakeWebSocket()
        stt._ws = ws

        asyncio.run(stt.close())

        assert json.loads(ws.sent[0]) == {"type": "CloseStream"}
        assert ws.closed is True

    def test_cancels_keepalive_task(self, stt):
        async def scenario():
            stt._ws = _FakeWebSocket()
            stt._keepalive_task = asyncio.ensure_future(asyncio.sleep(10))
            await stt.close()
            await asyncio.sleep(0)  # let the cancellation actually propagate
            assert stt._keepalive_task.cancelled()

        asyncio.run(scenario())

    def test_waits_for_listen_task_to_drain_final_results(self, stt):
        async def scenario():
            stt._ws = _FakeWebSocket()
            drained = asyncio.Event()

            async def fake_listen():
                drained.set()

            stt._listen_task = asyncio.ensure_future(fake_listen())
            await stt.close()
            assert drained.is_set()

        asyncio.run(scenario())

    def test_cancels_listen_task_if_it_never_finishes(self, stt, monkeypatch):
        monkeypatch.setattr("src.stt.deepgram_provider._CLOSE_DRAIN_TIMEOUT_S", 0.05)

        async def scenario():
            stt._ws = _FakeWebSocket()

            async def hangs_forever():
                await asyncio.sleep(10)

            stt._listen_task = asyncio.ensure_future(hangs_forever())
            await stt.close()
            assert stt._listen_task.cancelled()

        asyncio.run(scenario())

    def test_close_without_ever_connecting_is_a_noop(self, stt):
        """No _ws, no tasks — close() must not raise."""
        asyncio.run(stt.close())
