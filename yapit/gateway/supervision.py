"""Makes the death of a long-lived background task visible."""

import asyncio
from collections.abc import Coroutine
from typing import Any

from loguru import logger

from yapit.gateway.metrics import log_error


async def supervised(name: str, coro: Coroutine[Any, Any, None]) -> None:
    """Run a background loop, reporting anything that ends it.

    These loops run for the process lifetime and handle transient errors
    internally, so anything escaping — or a plain return — means their work has
    silently stopped. The `error` event surfaces that in the health report.

    Deliberately does not restart: a crash here means an unforeseen defect,
    which a restart loop would mask.

    Requires the wrapped loop to let `CancelledError` propagate. A loop that
    catches it and returns is indistinguishable from one that died, and will be
    reported on every clean shutdown.
    """
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception(f"Background task {name} crashed: {e}")
        await log_error(f"Background task {name} crashed: {e}")
        return
    logger.error(f"Background task {name} exited unexpectedly")
    await log_error(f"Background task {name} exited unexpectedly")
