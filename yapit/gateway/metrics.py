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
import contextlib
import json
import time
import traceback
from collections import deque
from datetime import UTC, datetime
from typing import Any

import asyncpg
from loguru import logger

# Global connection pool, initialized on startup
_pool: asyncpg.Pool | None = None
_database_url: str | None = None
_write_queue: asyncio.Queue[dict[str, Any]] | None = None
_writer_task: asyncio.Task[None] | None = None

BATCH_INTERVAL_S = 5.0
HEARTBEAT_INTERVAL_S = 3600.0  # longest a live writer leaves metrics_event quiet; scripts/metrics_freshness.py reads it
MAX_PENDING_EVENTS = 10_000  # buffer cap while the DB is unreachable; oldest dropped first
RETRY_MIN_DELAY_S = 5.0
RETRY_MAX_DELAY_S = 60.0
DOWN_LOG_INTERVAL_S = 600.0


async def init_metrics_db(database_url: str | None) -> None:
    """Initialize metrics database connection pool. Call once on startup.

    Failure is non-fatal: the writer loop keeps retrying, so a metrics DB that
    is briefly unavailable during a deploy doesn't disable metrics for the
    process lifetime.
    """
    global _pool, _database_url
    _database_url = database_url
    if not database_url:
        return
    try:
        _pool = await _create_pool()
    except Exception as e:
        logger.error(f"Metrics DB unavailable at startup ({e}); writer will keep retrying")
        _pool = None


async def _create_pool() -> asyncpg.Pool:
    assert _database_url
    pool = await asyncpg.create_pool(_database_url, min_size=1, max_size=5, timeout=10)
    assert pool is not None
    return pool


async def start_metrics_writer() -> None:
    """Start background writer task. Call after init_metrics_db."""
    global _write_queue, _writer_task
    if not _database_url:
        return  # No metrics DB configured, skip writer
    from yapit.gateway.supervision import supervised  # local import: supervision logs through this module

    _write_queue = asyncio.Queue()
    _writer_task = asyncio.create_task(supervised("metrics-writer", _writer_loop()))


async def stop_metrics_writer() -> None:
    """Stop background writer and flush pending events."""
    global _writer_task, _pool

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
    """Background task that batches writes to TimescaleDB.

    Failures (connect or write) don't kill metrics: events buffer in a bounded
    deque and each tick retries with backoff until the DB is reachable again.

    An idle writer proves it is alive: once HEARTBEAT_INTERVAL_S passes without a
    successful write (and on its first idle tick), it writes a `heartbeat` event,
    so a live pipeline never leaves a longer gap in metrics_event.
    """
    global _pool
    queue = _write_queue
    assert queue is not None

    pending: deque[dict[str, Any]] = deque(maxlen=MAX_PENDING_EVENTS)
    dropped = 0
    down_since: float | None = None
    last_attempt = 0.0
    last_down_log = 0.0
    last_write = float("-inf")
    retry_delay = RETRY_MIN_DELAY_S

    while True:
        try:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=BATCH_INTERVAL_S)
                events = [event]
                while not queue.empty():
                    try:
                        events.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                for e in events:
                    if len(pending) == MAX_PENDING_EVENTS:
                        dropped += 1
                    pending.append(e)
            except TimeoutError:
                pass

            now = time.monotonic()
            if not pending and now - last_write >= HEARTBEAT_INTERVAL_S:
                pending.append({"event_type": "heartbeat"})
            if not pending:
                continue

            if down_since is not None and now - last_attempt < retry_delay:
                continue
            last_attempt = now

            try:
                if _pool is None:
                    _pool = await _create_pool()
                await _write_batch(list(pending))
            except Exception as e:
                if down_since is None:
                    down_since = now
                    last_down_log = now
                    logger.error(f"Metrics DB write failed ({e}); buffering events and retrying")
                elif now - last_down_log >= DOWN_LOG_INTERVAL_S:
                    last_down_log = now
                    logger.error(
                        f"Metrics DB still unavailable after {now - down_since:.0f}s ({e}); "
                        f"{len(pending)} events buffered, {dropped} dropped"
                    )
                retry_delay = min(retry_delay * 2, RETRY_MAX_DELAY_S)
                continue

            if down_since is not None:
                outage_s = round(now - down_since)
                logger.info(
                    f"Metrics DB recovered after {outage_s}s; "
                    f"flushed {len(pending)} buffered events ({dropped} dropped)"
                )
                await log_warning(
                    "Metrics DB outage recovered",
                    outage_seconds=outage_s,
                    events_flushed=len(pending),
                    events_dropped=dropped,
                )
                down_since = None
                dropped = 0
            retry_delay = RETRY_MIN_DELAY_S
            last_write = now
            pending.clear()

        except asyncio.CancelledError:
            if pending and _pool:
                with contextlib.suppress(Exception):
                    await _write_batch(list(pending))
            raise


async def _write_batch(events: list[dict[str, Any]]) -> None:
    """Write a batch of events to TimescaleDB."""
    if not _pool:
        return

    columns = [
        "timestamp",
        "event_type",
        # Synthesis/detection
        "model_slug",
        "voice_slug",
        "variant_hash",
        "text_length",
        "queue_wait_ms",
        "worker_latency_ms",
        "total_latency_ms",
        "audio_duration_ms",
        "cache_hit",
        "queue_depth",
        # Worker/queue
        "worker_id",
        "queue_type",
        "retry_count",
        # LLM/extraction
        "processor_slug",
        "page_idx",
        "prompt_token_count",
        "candidates_token_count",
        "thoughts_token_count",
        "cached_content_token_count",
        "total_token_count",
        # Request
        "endpoint",
        "method",
        "status_code",
        "duration_ms",
        # Context
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
            event.get("timestamp", datetime.now(UTC)),
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
            event.get("queue_depth"),
            event.get("worker_id"),
            event.get("queue_type"),
            event.get("retry_count"),
            event.get("processor_slug"),
            event.get("page_idx"),
            event.get("prompt_token_count"),
            event.get("candidates_token_count"),
            event.get("thoughts_token_count"),
            event.get("cached_content_token_count"),
            event.get("total_token_count"),
            event.get("endpoint"),
            event.get("method"),
            event.get("status_code"),
            event.get("duration_ms"),
            event.get("user_id"),
            event.get("document_id"),
            event.get("request_id"),
            event.get("block_idx"),
            json.dumps(data, default=str) if data else None,
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
