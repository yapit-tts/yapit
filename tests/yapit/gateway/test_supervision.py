"""Tests for background task supervision.

The distinction that matters: a cancelled task is a clean shutdown and must stay
silent, anything else means the loop is gone and must be reported. Getting this
backwards either hides a dead consumer or pages on every deploy.
"""

import asyncio

import pytest

from yapit.gateway.supervision import supervised


@pytest.fixture
def reported(monkeypatch):
    """Capture `error` events instead of writing them to the metrics queue."""
    messages = []

    async def fake_log_error(message, **kwargs):
        messages.append(message)

    monkeypatch.setattr("yapit.gateway.supervision.log_error", fake_log_error)
    return messages


@pytest.mark.asyncio
async def test_crash_is_reported(reported):
    async def loop():
        raise RuntimeError("redis exploded")

    await supervised("billing-consumer", loop())

    assert len(reported) == 1
    assert "billing-consumer" in reported[0]
    assert "redis exploded" in reported[0]


@pytest.mark.asyncio
async def test_early_return_is_reported(reported):
    async def loop():
        return

    await supervised("batch-poller", loop())

    assert len(reported) == 1
    assert "exited unexpectedly" in reported[0]


@pytest.mark.asyncio
async def test_cancellation_is_silent_and_propagates(reported):
    started = asyncio.Event()

    async def loop():
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(supervised("result-consumer", loop()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert reported == []


@pytest.mark.asyncio
async def test_loop_that_swallows_cancellation_is_reported(reported):
    """Guards the contract: swallowing CancelledError pages on every clean shutdown."""
    started = asyncio.Event()

    async def swallows_cancel():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(supervised("openai-tts-dispatcher", swallows_cancel()))
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(reported) == 1
    assert "exited unexpectedly" in reported[0]
