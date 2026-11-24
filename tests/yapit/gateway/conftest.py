import asyncio

import pytest

from yapit.gateway import metrics


@pytest.fixture
def metrics_events(monkeypatch):
    """The metrics events written from now on, as the writer would take them: each call gives those since the last."""
    queue: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(metrics, "_write_queue", queue)

    def taken() -> list[dict]:
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return events

    return taken
