"""The backoff must escalate when the *work* fails, not only when the read fails.

A supervisor loop whose read keeps succeeding while its downstream dies — Postgres
or SQLite unreachable — is the common outage shape. If the backoff resets on the
read, every iteration sleeps the base delay and the loop errors ~1×/s forever,
which is the log-and-metrics flood the backoff exists to bound.
"""

import asyncio

import pytest

from yapit.contracts import TTS_PERSIST
from yapit.gateway.cache_persister import run_cache_persister


class _AlwaysHasWork:
    """Redis stub: one hash per wake, so the read always succeeds."""

    async def brpop(self, key, timeout=None):
        return (TTS_PERSIST.encode(), b"deadbeef")

    async def rpop(self, key):
        return None

    async def mget(self, keys):
        return [b"audio" for _ in keys]


class _BrokenCache:
    async def store(self, *args, **kwargs):
        return None

    async def commit(self):
        raise OSError("database or disk is full")


@pytest.mark.asyncio
async def test_backoff_escalates_when_commit_keeps_failing(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(seconds):
        delays.append(seconds)
        if len(delays) >= 4:
            raise asyncio.CancelledError

    monkeypatch.setattr("yapit.gateway.backoff.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("yapit.gateway.cache_persister.log_error", _noop)
    monkeypatch.setattr("yapit.gateway.cache_persister.log_event", _noop)

    with pytest.raises(asyncio.CancelledError):
        await run_cache_persister(_AlwaysHasWork(), _BrokenCache())  # ty: ignore[invalid-argument-type]

    assert delays == sorted(delays), f"backoff must not go backwards: {delays}"
    assert delays[-1] > delays[0], f"backoff pinned at base delay: {delays}"


async def _noop(*args, **kwargs):
    return None
