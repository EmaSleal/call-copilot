"""
Unit tests for src.processing.tool_extractor._run_coro_sync() — the
bridge that lets ingest_tools()/import_from_tech_scout() run their
async embedding step from synchronous callers.

Bugfix: import_from_tech_scout() is called synchronously from
SettingsScreen._sync_tech_scout() (the "Sync tech-scout" button in the
Settings modal), which runs inside Textual's own asyncio event loop.
Calling asyncio.run() there raised "RuntimeError: asyncio.run() cannot
be called from a running event loop" — a crash on every click. Confirmed
against a real user-reported traceback. ingest_tools() calls the exact
same asyncio.run() pattern but from a plain sync context (no loop
running), which is why it never surfaced there.
"""

import asyncio

import pytest

from src.processing.tool_extractor import _run_coro_sync


async def _return_value(value):
    return value


class TestRunCoroSyncOutsideALoop:
    def test_runs_and_returns_the_coroutine_result(self):
        result = _run_coro_sync(_return_value(42))
        assert result == 42


class TestRunCoroSyncInsideARunningLoop:
    def test_does_not_raise_and_returns_the_coroutine_result(self):
        async def caller():
            # We are now inside a running event loop — plain asyncio.run()
            # would raise here. _run_coro_sync must not.
            return _run_coro_sync(_return_value("ok"))

        result = asyncio.run(caller())
        assert result == "ok"

    def test_propagates_exceptions_from_the_coroutine(self):
        async def boom():
            raise ValueError("embedding failed")

        async def caller():
            _run_coro_sync(boom())

        with pytest.raises(ValueError, match="embedding failed"):
            asyncio.run(caller())
