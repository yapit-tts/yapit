"""Tests for the self-healing metrics writer.

The contract that matters: a metrics DB that is unreachable — at startup or
mid-life — must not disable metrics for the process lifetime. Events buffer
(bounded) and flush on recovery; only overflow beyond the cap is lost.
"""

import asyncio
import json
import time

import pytest

from yapit.gateway import metrics


class FakePool:
    def __init__(self, db):
        self._db = db

    def acquire(self):
        return _FakeAcquire(self._db)

    async def close(self):
        pass


class _FakeAcquire:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def executemany(self, sql, rows):
        if not self._db["up"]:
            raise ConnectionError("db went away")
        self._db["rows"].extend(rows)


@pytest.fixture
def db(monkeypatch):
    """Fake DB reachable via a switchable `up` flag; started writer is torn down."""
    state = {"up": True, "rows": []}

    async def fake_create_pool(*args, **kwargs):
        if not state["up"]:
            raise ConnectionError("connection refused")
        return FakePool(state)

    monkeypatch.setattr(metrics.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(metrics, "_pool", None)
    monkeypatch.setattr(metrics, "_write_queue", None)
    monkeypatch.setattr(metrics, "_writer_task", None)
    monkeypatch.setattr(metrics, "_database_url", "postgresql://fake")
    monkeypatch.setattr(metrics, "BATCH_INTERVAL_S", 0.01)
    monkeypatch.setattr(metrics, "RETRY_MIN_DELAY_S", 0.0)
    monkeypatch.setattr(metrics, "RETRY_MAX_DELAY_S", 0.0)
    return state


@pytest.fixture
async def stop_writer():
    yield
    if metrics._writer_task:
        metrics._writer_task.cancel()
        await asyncio.gather(metrics._writer_task, return_exceptions=True)


async def eventually(cond, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def event_types(db):
    return [row[1] for row in db["rows"]]


@pytest.mark.asyncio
async def test_healthy_path_writes_events(db, stop_writer):
    await metrics.start_metrics_writer()
    await metrics.log_event("synthesis_complete", text_length=42)

    await eventually(lambda: "synthesis_complete" in event_types(db))


@pytest.mark.asyncio
async def test_db_down_at_startup_recovers_without_restart(db, stop_writer):
    """The 2026-08-07 outage: DB unreachable when the gateway starts. Events
    logged during the outage must flush once the DB is reachable.
    """
    db["up"] = False
    await metrics.init_metrics_db("postgresql://fake")
    await metrics.start_metrics_writer()

    await metrics.log_event("synthesis_complete", text_length=1)
    await metrics.log_event("synthesis_complete", text_length=2)
    await asyncio.sleep(0.1)
    assert db["rows"] == []

    db["up"] = True
    await eventually(lambda: event_types(db).count("synthesis_complete") == 2)
    assert "warning" in event_types(db)  # outage-recovered event


@pytest.mark.asyncio
async def test_midlife_outage_buffers_and_flushes(db, stop_writer):
    await metrics.start_metrics_writer()
    await metrics.log_event("synthesis_complete", text_length=1)
    await eventually(lambda: event_types(db).count("synthesis_complete") == 1)

    db["up"] = False
    await metrics.log_event("synthesis_complete", text_length=2)
    await metrics.log_event("synthesis_complete", text_length=3)
    await asyncio.sleep(0.1)
    assert event_types(db).count("synthesis_complete") == 1

    db["up"] = True
    await eventually(lambda: event_types(db).count("synthesis_complete") == 3)


@pytest.mark.asyncio
async def test_buffer_overflow_drops_oldest_and_reports(db, stop_writer, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_PENDING_EVENTS", 3)
    db["up"] = False
    await metrics.start_metrics_writer()

    for i in range(5):
        await metrics.log_event("synthesis_complete", text_length=i)
        await asyncio.sleep(0.03)  # let the writer drain each into the bounded buffer

    db["up"] = True
    await eventually(lambda: "warning" in event_types(db))

    # newest 3 survive, oldest 2 dropped
    kept = [row[5] for row in db["rows"] if row[1] == "synthesis_complete"]  # text_length column
    assert kept == [2, 3, 4]
    warning_data = json.loads(next(row[-1] for row in db["rows"] if row[1] == "warning"))
    assert warning_data["events_dropped"] == 2


@pytest.mark.asyncio
async def test_idle_writer_heartbeats(db, stop_writer, monkeypatch):
    """A writer with nothing to write still proves it is alive, so a quiet day and a
    dead pipeline stop looking the same in metrics_event.
    """
    monkeypatch.setattr(metrics, "HEARTBEAT_INTERVAL_S", 0.05)
    await metrics.start_metrics_writer()

    await eventually(lambda: event_types(db).count("heartbeat") >= 3)
    assert set(event_types(db)) == {"heartbeat"}


@pytest.mark.asyncio
async def test_cancellation_propagates(db, stop_writer):
    await metrics.start_metrics_writer()
    task = metrics._writer_task
    assert task is not None
    await asyncio.sleep(0)  # let the loop start before cancelling
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled() or task.done()
