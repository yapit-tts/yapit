"""Tests for the supervisor-loop backoff schedule."""

import pytest

from yapit.gateway.backoff import Backoff


@pytest.fixture
def slept(monkeypatch):
    """Record sleep durations instead of actually waiting."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr("yapit.gateway.backoff.asyncio.sleep", fake_sleep)
    return recorded


@pytest.mark.asyncio
async def test_delay_doubles_and_caps(slept):
    backoff = Backoff(base_s=1, max_s=8, jitter=False)
    for _ in range(6):
        await backoff.sleep()

    assert slept == [1, 2, 4, 8, 8, 8]


@pytest.mark.asyncio
async def test_reset_returns_to_base(slept):
    backoff = Backoff(base_s=1, max_s=8, jitter=False)
    for _ in range(3):
        await backoff.sleep()
    assert backoff.delay_s == 8

    backoff.reset()
    await backoff.sleep()
    assert slept[-1] == 1


@pytest.mark.asyncio
async def test_jitter_stays_within_one_and_a_half_delays(slept):
    backoff = Backoff(base_s=2, max_s=8, jitter=True)
    for _ in range(4):
        await backoff.sleep()

    for actual, scheduled in zip(slept, [2, 4, 8, 8]):
        assert scheduled <= actual <= scheduled * 1.5


def test_base_above_max_is_rejected():
    with pytest.raises(AssertionError):
        Backoff(base_s=30, max_s=10)
