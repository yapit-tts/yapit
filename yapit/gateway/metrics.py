"""Metrics logging to TimescaleDB for observability and trend analysis.

Usage:
    from yapit.gateway.metrics import log_event

    # In async code:
    await log_event(
        "synthesis_complete",
        model_slug="kokoro-cpu",
        worker_latency_ms=150,
        cache_hit=False,
    )

The database has automatic:
- Compression (chunks older than 7 days)
- Retention (raw data deleted after 30 days)
- Continuous aggregates (hourly kept 1 year, daily kept forever)

Query examples:
    -- P95 latency by model, last 7 days
    SELECT model_slug,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY worker_latency_ms) as p95
    FROM metrics_event
    WHERE event_type = 'synthesis_complete'
      AND timestamp > NOW() - INTERVAL '7 days'
    GROUP BY model_slug;

    -- Use hourly aggregates for longer ranges
    SELECT bucket, model_slug, p95_total_latency_ms
    FROM metrics_hourly
    WHERE event_type = 'synthesis_complete'
      AND bucket > NOW() - INTERVAL '30 days';
"""

import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Any

import asyncpg

# Global connection pool, initialized on startup
_pool: asyncpg.Pool | None = None
_write_queue: asyncio.Queue[dict[str, Any]] | None = None
_writer_task: asyncio.Task[None] | None = None


async def init_metrics_db(database_url: str) -> None:
    """Initialize metrics database connection pool. Call once on startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=5,
    )


async def start_metrics_writer() -> None:
    """Start background writer task. Call after init_metrics_db."""
    global _write_queue, _writer_task
    _write_queue = asyncio.Queue()
    _writer_task = asyncio.create_task(_writer_loop())


async def stop_metrics_writer() -> None:
    """Stop background writer and flush pending events."""
    global _writer_task, _write_queue, _pool

    if _writer_task:
        _writer_task.cancel()
        try:
            await _writer_task
        except asyncio.CancelledError:
            pass
        _writer_task = None

    # Flush remaining events
    if _write_queue and _pool:
        events = []
        while not _write_queue.empty():
            try:
                events.append(_write_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if events:
            await _write_batch(events)

    # Close connection pool
    if _pool:
        await _pool.close()
        _pool = None


async def _writer_loop() -> None:
    """Background task that batches writes to TimescaleDB."""
    batch: list[dict[str, Any]] = []
    batch_interval = 5.0  # seconds

    while True:
        try:
            try:
                event = await asyncio.wait_for(_write_queue.get(), timeout=batch_interval)  # type: ignore[union-attr]
                batch.append(event)
                while not _write_queue.empty():  # type: ignore[union-attr]
                    try:
                        batch.append(_write_queue.get_nowait())  # type: ignore[union-attr]
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                pass

            if batch:
                await _write_batch(batch)
                batch = []

        except asyncio.CancelledError:
            if batch:
                await _write_batch(batch)
            raise
        except Exception:
            traceback.print_exc()
            batch = []


async def _write_batch(events: list[dict[str, Any]]) -> None:
    """Write a batch of events to TimescaleDB."""
    if not _pool:
        return

    columns = [
        "timestamp",
        "event_type",
        "model_slug",
        "voice_slug",
        "variant_hash",
        "text_length",
        "queue_wait_ms",
        "worker_latency_ms",
        "total_latency_ms",
        "audio_duration_ms",
        "cache_hit",
        "processor_route",
        "queue_depth",
        "endpoint",
        "method",
        "status_code",
        "duration_ms",
        "user_id",
        "document_id",
        "request_id",
        "block_idx",
        "data",
    ]

    rows = []
    for event in events:
        data = event.get("data")
        row = (
            event.get("timestamp", datetime.now(timezone.utc)),
            event.get("event_type"),
            event.get("model_slug"),
            event.get("voice_slug"),
            event.get("variant_hash"),
            event.get("text_length"),
            event.get("queue_wait_ms"),
            event.get("worker_latency_ms"),
            event.get("total_latency_ms"),
            event.get("audio_duration_ms"),
            event.get("cache_hit"),
            event.get("processor_route"),
            event.get("queue_depth"),
            event.get("endpoint"),
            event.get("method"),
            event.get("status_code"),
            event.get("duration_ms"),
            event.get("user_id"),
            event.get("document_id"),
            event.get("request_id"),
            event.get("block_idx"),
            json.dumps(data) if data else None,
        )
        rows.append(row)

    placeholders = ", ".join([f"${i + 1}" for i in range(len(columns))])
    column_names = ", ".join(columns)
    sql = f"INSERT INTO metrics_event ({column_names}) VALUES ({placeholders})"

    async with _pool.acquire() as conn:
        await conn.executemany(sql, rows)


async def log_event(event_type: str, **kwargs: Any) -> None:
    """Log a metrics event asynchronously.

    Args:
        event_type: Event type (e.g., 'synthesis_complete', 'request_complete')
        **kwargs: Event fields matching the schema columns, plus optional 'data' dict
    """
    if _write_queue is None:
        return

    event = {"event_type": event_type, **kwargs}
    await _write_queue.put(event)


async def log_error(message: str, **context: Any) -> None:
    """Log an error event with traceback."""
    tb = traceback.format_exc()
    await log_event(
        "error",
        data={
            "message": message,
            "traceback": tb if tb != "NoneType: None\n" else None,
            **context,
        },
    )


async def log_warning(message: str, **context: Any) -> None:
    """Log a warning event."""
    await log_event("warning", data={"message": message, **context})
