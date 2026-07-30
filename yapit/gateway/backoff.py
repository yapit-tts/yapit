"""Exponential backoff schedule, shared by the long-lived supervisor loops.

A loop that retries a persistently-failing operation at a fixed 1s interval
emits one log line and one metrics row per second. A single wedged consumer
once produced 168k metrics rows and ~600MB of logs per day, which collapsed
log retention from months to hours and buried every unrelated error.
Backing off keeps the failure visible without drowning out everything else.

Unbounded by design: consumer loops must never give up. Bounded retries of a
single call (document extraction, TTS adapters) compute the same schedule
inline in `document/processors/base.py`.
"""

import asyncio
import random

BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 60.0


class Backoff:
    def __init__(
        self,
        base_s: float = BASE_DELAY_SECONDS,
        max_s: float = MAX_DELAY_SECONDS,
        jitter: bool = True,
    ) -> None:
        assert 0 < base_s <= max_s
        self.base_s = base_s
        self.max_s = max_s
        self.jitter = jitter
        self.delay_s = base_s

    def reset(self) -> None:
        self.delay_s = self.base_s

    async def sleep(self) -> None:
        delay = self.delay_s
        if self.jitter:
            delay += random.uniform(0, delay * 0.5)
        await asyncio.sleep(delay)
        self.delay_s = min(self.delay_s * 2, self.max_s)
