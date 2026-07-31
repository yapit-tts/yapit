"""Tests for the shared exponential backoff schedule."""

import pytest

from yapit.gateway.backoff import Backoff, delay_for


@pytest.fixture
def slept(monkeypatch):
    """Record sleep durations instead of actually waiting."""
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr("yapit.gateway.backoff.asyncio.sleep", fake_sleep)
    return recorded


def test_delay_for_doubles_and_caps():
    delays = [delay_for(attempt, base_s=1, max_s=8, jitter=False) for attempt in range(6)]
    assert delays == [1, 2, 4, 8, 8, 8]


def test_delay_for_jitter_stays_within_one_and_a_half():
    for attempt in range(5):
        plain = delay_for(attempt, base_s=2, max_s=8, jitter=False)
        jittered = delay_for(attempt, base_s=2, max_s=8, jitter=True)
        assert plain <= jittered <= plain * 1.5


def test_delay_for_huge_attempt_stays_capped():
    """A loop wedged for days must not build absurd intermediate ints."""
    assert delay_for(10_000, base_s=1, max_s=60, jitter=False) == 60


def test_delay_for_rejects_bad_input():
    with pytest.raises(AssertionError):
        delay_for(-1, base_s=1, max_s=10)
    with pytest.raises(AssertionError):
        delay_for(0, base_s=30, max_s=10)


@pytest.mark.asyncio
async def test_backoff_advances_across_sleeps(slept):
    backoff = Backoff(base_s=1, max_s=8, jitter=False)
    for _ in range(6):
        await backoff.sleep()

    assert slept == [1, 2, 4, 8, 8, 8]


@pytest.mark.asyncio
async def test_backoff_reset_returns_to_base(slept):
    backoff = Backoff(base_s=1, max_s=8, jitter=False)
    for _ in range(3):
        await backoff.sleep()

    backoff.reset()
    assert await backoff.sleep() == 1


@pytest.mark.asyncio
async def test_backoff_sleep_returns_delay_for_logging(slept):
    backoff = Backoff(base_s=2, max_s=8, jitter=False)
    assert await backoff.sleep() == 2
    assert await backoff.sleep() == 4


def test_backoff_rejects_base_above_max():
    with pytest.raises(AssertionError):
        Backoff(base_s=30, max_s=10)
