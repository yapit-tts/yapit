"""Exponential backoff schedule.

One definition of the schedule, two ways to consume it:

- `delay_for(attempt)` — stateless, for bounded `for attempt in range(N)` retries
  of a single call. The delay is a pure function of the loop counter.
- `Backoff` — stateful, for the unbounded supervisor loops, which have no attempt
  counter and must reset once the operation succeeds again.

Callers pass their own tuning: bounded API retries cap lower than a consumer loop,
which trades latency for not flooding logs and metrics with a stuck failure.
"""

import asyncio
import random

DEFAULT_BASE_DELAY_S = 1.0
DEFAULT_MAX_DELAY_S = 60.0

# Retry policy for outbound calls to external AI/TTS APIs. Caps below the
# supervisor-loop default because a user is waiting on the result.
API_RETRYABLE_STATUS_CODES = {429, 500, 503, 504}
API_MAX_RETRIES = 6
API_BASE_DELAY_S = 1.0
API_MAX_DELAY_S = 30.0

# Bounds the exponent so a long-wedged loop doesn't build absurd intermediate ints.
_MAX_EXPONENT = 30


def delay_for(attempt: int, base_s: float, max_s: float, jitter: bool = True) -> float:
    """Seconds to wait before retrying 0-indexed `attempt`.

    Tuning is required rather than defaulted — API retries and supervisor loops
    cap at different ceilings, and inheriting the wrong one is silent.
    """
    assert attempt >= 0
    assert 0 < base_s <= max_s
    delay = min(base_s * (2 ** min(attempt, _MAX_EXPONENT)), max_s)
    if jitter:
        delay += random.uniform(0, delay * 0.5)
    return delay


class Backoff:
    def __init__(
        self,
        base_s: float = DEFAULT_BASE_DELAY_S,
        max_s: float = DEFAULT_MAX_DELAY_S,
        jitter: bool = True,
    ) -> None:
        assert 0 < base_s <= max_s
        self.base_s = base_s
        self.max_s = max_s
        self.jitter = jitter
        self.attempt = 0

    @classmethod
    def from_interval(cls, interval_s: float, jitter: bool = True) -> "Backoff":
        """For a loop with a natural cadence: start there, never retry faster."""
        return cls(base_s=interval_s, max_s=max(DEFAULT_MAX_DELAY_S, interval_s), jitter=jitter)

    def reset(self) -> None:
        self.attempt = 0

    async def sleep(self) -> float:
        delay = delay_for(self.attempt, self.base_s, self.max_s, self.jitter)
        await asyncio.sleep(delay)
        self.attempt += 1
        return delay
