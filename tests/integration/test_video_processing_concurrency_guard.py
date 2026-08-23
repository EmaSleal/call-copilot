"""Integration test for the point-5 (docs/next-steps/feature-proposals.md)
concurrency=1 guard: only one video-processing job may be "processing" at
a time.

This specifically targets a real race condition, not a hypothetical one —
Hallazgo 1 of the point-5 empirical validation confirmed Claude Desktop
can run 2+ instances of the same MCP server concurrently as separate OS
processes, each with its own Python interpreter and DB connection. A
naive "SELECT to check, then INSERT if clear" guard has a classic
time-of-check-to-time-of-use race: two processes can both see "nothing
processing" before either writes, and both start a job. Real OS
processes are used here (multiprocessing with the "fork" context), not
threads — a threading-only test would not exercise this, since it
wouldn't prove the guard holds across independent sqlite3 connections
from independent processes.
"""

import multiprocessing as mp

from src.db import database


def _worker(db_path, barrier, results, idx) -> None:
    from src.db.video_sessions import try_start_processing_session

    database.DB_PATH = db_path
    barrier.wait()
    session = try_start_processing_session(f"title-{idx}", f"https://x/{idx}")
    results[idx] = session.id if session else None


class TestConcurrencyGuardRace:
    def test_only_one_concurrent_process_wins_the_processing_slot(self, tmp_path):
        db_path = tmp_path / "race.db"
        database.DB_PATH = db_path
        database.init_db()

        ctx = mp.get_context("fork")
        n = 8
        barrier = ctx.Barrier(n)
        manager = ctx.Manager()
        results = manager.dict()

        procs = [
            ctx.Process(target=_worker, args=(db_path, barrier, results, i))
            for i in range(n)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=15)
            assert not p.is_alive(), "worker process hung"

        winners = [v for v in results.values() if v is not None]
        assert len(results) == n
        assert len(winners) == 1

    def test_second_call_is_rejected_once_a_session_is_processing(self, tmp_path):
        from src.db.video_sessions import try_start_processing_session

        database.DB_PATH = tmp_path / "sequential.db"
        database.init_db()

        first = try_start_processing_session("first", "https://x/1")
        second = try_start_processing_session("second", "https://x/2")

        assert first is not None
        assert second is None

    def test_succeeds_again_once_the_processing_session_is_resolved(self, tmp_path):
        from src.db.video_sessions import (
            try_start_processing_session,
            update_session_status,
        )

        database.DB_PATH = tmp_path / "sequential2.db"
        database.init_db()

        first = try_start_processing_session("first", "https://x/1")
        update_session_status(first.id, "done", html_report="/tmp/report.html")

        second = try_start_processing_session("second", "https://x/2")

        assert second is not None
