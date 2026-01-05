"""Metrics logging to SQLite for observability and trend analysis.

Usage:
    from yapit.gateway.metrics import log_event

    # In async code:
    await log_event(
        "synthesis_complete",
        model_slug="kokoro-cpu",
        worker_latency_ms=150,
        cache_hit=False,
    )

Query examples:
    # P95 latency by model, last 7 days
    SELECT model_slug, AVG(worker_latency_ms)
    FROM metrics_event
    WHERE event_type = 'synthesis_complete'
      AND timestamp > datetime('now', '-7 days')
    GROUP BY model_slug;

    # Cache hit rate
    SELECT model_slug,
           SUM(CASE WHEN cache_hit THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as hit_rate
    FROM metrics_event WHERE event_type = 'synthesis_complete'
    GROUP BY model_slug;
"""

import asyncio
import json
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

# Global connection, initialized on startup
_db_path: Path | None = None
_write_queue: asyncio.Queue[dict[str, Any]] | None = None
_writer_task: asyncio.Task[None] | None = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics_event (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,

    -- Synthesis fields
    model_slug TEXT,
    voice_slug TEXT,
    variant_hash TEXT,
    text_length INTEGER,
    queue_wait_ms INTEGER,
    worker_latency_ms INTEGER,
    total_latency_ms INTEGER,
    audio_duration_ms INTEGER,
    cache_hit BOOLEAN,
    processor_route TEXT,
    queue_depth INTEGER,

    -- Request fields
    endpoint TEXT,
    method TEXT,
    status_code INTEGER,
    duration_ms INTEGER,

    -- Context
    user_id TEXT,
    document_id TEXT,
    request_id TEXT,
    block_idx INTEGER,

    -- Flexible data
    data JSON
);

CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics_event(timestamp);
CREATE INDEX IF NOT EXISTS idx_metrics_event_type ON metrics_event(event_type);
CREATE INDEX IF NOT EXISTS idx_metrics_model ON metrics_event(model_slug) WHERE model_slug IS NOT NULL;
"""


def init_metrics_db(db_path: Path | str) -> None:
    """Initialize metrics database. Call once on startup."""
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(_db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode=WAL")


async def start_metrics_writer() -> None:
    """Start background writer task. Call after init_metrics_db."""
    global _write_queue, _writer_task
    _write_queue = asyncio.Queue()
    _writer_task = asyncio.create_task(_writer_loop())


async def stop_metrics_writer() -> None:
    """Stop background writer and flush pending events."""
    global _writer_task, _write_queue
    if _writer_task:
        _writer_task.cancel()
        try:
            await _writer_task
        except asyncio.CancelledError:
            pass
        _writer_task = None

    # Flush remaining events
    if _write_queue and _db_path:
        events = []
        while not _write_queue.empty():
            try:
                events.append(_write_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if events:
            _write_batch(events)


async def _writer_loop() -> None:
    """Background task that batches writes to SQLite."""
    batch: list[dict[str, Any]] = []
    batch_interval = 5.0  # seconds — metrics don't need real-time visibility

    while True:
        try:
            # Collect events for up to batch_interval seconds
            try:
                event = await asyncio.wait_for(_write_queue.get(), timeout=batch_interval)  # type: ignore[union-attr]
                batch.append(event)
                # Grab any additional queued events
                while not _write_queue.empty():  # type: ignore[union-attr]
                    try:
                        batch.append(_write_queue.get_nowait())  # type: ignore[union-attr]
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                pass

            if batch:
                _write_batch(batch)
                batch = []

        except asyncio.CancelledError:
            # Final flush on shutdown
            if batch:
                _write_batch(batch)
            raise
        except Exception:
            # Log but don't crash the writer
            traceback.print_exc()
            batch = []


def _write_batch(events: list[dict[str, Any]]) -> None:
    """Write a batch of events to SQLite (sync, called from async context)."""
    if not _db_path:
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
        row = [
            event.get("timestamp", datetime.utcnow().isoformat()),
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
            json.dumps(event.get("data")) if event.get("data") else None,
        ]
        rows.append(row)

    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(columns)
    sql = f"INSERT INTO metrics_event ({column_names}) VALUES ({placeholders})"

    with sqlite3.connect(_db_path) as conn:
        conn.executemany(sql, rows)


async def log_event(event_type: str, **kwargs: Any) -> None:
    """Log a metrics event asynchronously.

    Args:
        event_type: Event type (e.g., 'synthesis_complete', 'request_complete')
        **kwargs: Event fields matching the schema columns, plus optional 'data' dict
    """
    if _write_queue is None:
        return  # Metrics not initialized

    event = {"event_type": event_type, **kwargs}
    await _write_queue.put(event)


def log_event_sync(event_type: str, **kwargs: Any) -> None:
    """Log a metrics event synchronously (for use in non-async contexts).
    Writes directly instead of queuing.
    """
    if not _db_path:
        return

    event = {"event_type": event_type, **kwargs}
    _write_batch([event])


async def log_error(message: str, **context: Any) -> None:
    """Log an error event with optional traceback."""
    tb = traceback.format_exc()
    await log_event(
        "error",
        data={"message": message, "traceback": tb if tb != "NoneType: None\n" else None, **context},
    )


async def log_warning(message: str, **context: Any) -> None:
    """Log a warning event."""
    await log_event("warning", data={"message": message, **context})
