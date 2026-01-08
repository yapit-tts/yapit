---
status: done
started: 2025-01-04
---

# Task: Logging & Observability Infrastructure

Related:
- [[monitoring-observability-logging]] (legacy plan) — prior brainstorming, historical reference
- [[operational-metrics-visibility]] — MERGED into this task
- [[user-stats-analytics]] — lower priority, not in scope

## Intent

Build logging infrastructure that enables:
1. **Debugging** — trace issues through request correlation IDs, error context
2. **Performance tuning** — measure latency at each stage (queue wait, worker, total)
3. **Trend analysis** — query weeks/months of per-event data for patterns
4. **Capacity planning** — queue depth, worker utilization, overflow usage

Key context: Single dev + LLM agents doing 90% of work. System must be:
- CLI-queryable (SQL, Python scripts)
- Persistent for months (per-event, not just aggregates)
- Low maintenance (no periodic jobs, no complex infra)
- Storage efficient (~1GB/month at 100K syntheses/day)

No Sentry/OpenTelemetry/Prometheus/Grafana — LLM agents do the analysis via SQL.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                   Gateway                        │
│                                                  │
│  Events (synthesis, requests, WS, errors)        │
│           │                    │                 │
│           ▼                    ▼                 │
│      loguru → stdout      async write → SQLite  │
│      (debug/info)         (metrics + errors)    │
└──────────────────────────────────────────────────┘
            │                         │
            ▼                         ▼
      docker logs              SQL queries
      (live tailing,           (debugging,
       ephemeral)              trends, analysis)
```

**stdout (loguru)**: Debug/info messages for live tailing. Ephemeral.
**SQLite**: Metrics events + warnings/errors with context. Persistent.

## SQLite Schema

```sql
CREATE TABLE metrics_event (
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
    processor_route TEXT,       -- 'local', 'runpod', 'overflow'
    queue_depth INTEGER,        -- queue length at event time

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

    -- Flexible data (tracebacks, extra context)
    data JSON
);

CREATE INDEX idx_timestamp ON metrics_event(timestamp);
CREATE INDEX idx_event_type ON metrics_event(event_type);
CREATE INDEX idx_model ON metrics_event(model_slug) WHERE model_slug IS NOT NULL;
```

## Event Catalog

| Event Type | Trigger | Key Fields |
|------------|---------|------------|
| `synthesis_queued` | Job pushed to Redis | variant_hash, model, queue_depth, block_idx |
| `synthesis_started` | Worker picks up job (after eviction check) | variant_hash, model, block_idx |
| `synthesis_complete` | Worker finishes | variant_hash, latencies, cache_hit, processor_route, block_idx |
| `synthesis_error` | Worker fails | variant_hash, error in data, block_idx |
| `eviction_triggered` | cursor_moved evicts blocks | document_id, cursor/window/evicted_indices in data |
| `eviction_skipped` | Worker skips evicted job | variant_hash, block_idx |
| `cache_hit` | Audio found in cache | variant_hash, model, block_idx |
| `ws_connect` | WebSocket opened | user_id |
| `ws_disconnect` | WebSocket closed | user_id, session_duration in data |
| `request_complete` | HTTP request done | endpoint, status_code, duration_ms |
| `document_parse` | Document processed | block_count, chars in data |
| `warning` | Warning logged | message, context in data |
| `error` | Exception caught | message, traceback in data |

## Implementation Plan

### Files to Create

1. `yapit/gateway/metrics.py` — SQLite connection, async writer, log_event() function
2. Update `yapit/gateway/__init__.py` — loguru setup, SQLite init on startup

### Instrumentation Points

| Location | Events |
|----------|--------|
| `api/v1/ws.py` | synthesis_queued, ws_connect, ws_disconnect |
| `processors/tts/base.py` | synthesis_complete, synthesis_error |
| Request middleware (new) | request_complete |
| `processors/document/*.py` | document_parse |
| `cache.py` | cache_hit, cache_miss |
| Exception handlers | error, warning |

### Queue Depth Capture

Event-based, not periodic. When queueing a job:
```python
queue_depth = await redis.llen(queue_name)
log_event('synthesis_queued', queue_depth=queue_depth, ...)
```

### Async Writing

SQLite writes should not block request handling:
- Option A: asyncio task queue, batch writes
- Option B: aiosqlite with connection pool
- Option C: synchronous writes in background thread

## Decisions Made

| Question | Decision | Rationale |
|----------|----------|-----------|
| Storage format | SQLite | SQL queries natural for LLM agents, fast aggregation |
| Log persistence | SQLite for metrics/errors, stdout for debug/info | Debug is ephemeral, errors need investigation |
| Aggregation | Per-event, no pre-aggregation | Storage is cheap, can aggregate later, keeps flexibility |
| Retention | Unlimited until manual cleanup | Simple, deal with storage when it becomes an issue |
| Queue monitoring | Event-based (capture depth on queue/dequeue) | No periodic tasks |
| External tools | None (no Sentry/Prometheus/etc) | LLM agents query SQLite directly |

## Sources

- [[monitoring-observability-logging]] — Historical reference for event ideas, production debugging learnings

## Implementation Progress

**Completed:**
- `yapit/gateway/metrics.py` — SQLite DB with async batched writer (5s interval)
- `yapit/gateway/__init__.py` — loguru setup, metrics init/shutdown in lifespan
- `yapit/gateway/config.py` — `metrics_db_path` setting
- `.env.dev`, `.env.prod` — metrics DB path configuration
- `docker-compose.dev.yml`, `docker-compose.prod.yml` — metrics volume mounts
- `api/v1/ws.py` — synthesis_queued, cache_hit, ws_connect, ws_disconnect, eviction_triggered events
- `processors/tts/base.py` — synthesis_complete, synthesis_error, synthesis_started, eviction_skipped events
- Verified working: 114 synthesis_queued, 107 synthesis_complete, 19 ws_connect, 14 cache_hit events captured
- **Loguru migration** — All 11 modules migrated from stdlib logging to loguru (2025-01-05)
- **Eviction bug fixes** — All 4 fixes implemented (2025-01-05)
- **Schema enhancements** (2025-01-05):
  - Added `block_idx` column to metrics schema
  - Added `synthesis_started` event (measures queue wait vs worker time)
  - Added `block_idx` to all synthesis events (queued, started, complete, error, cache_hit, eviction_skipped)
- **Dev workflow** — `make dev-cpu` now auto-deletes metrics.db (fresh schema on restart)
- **Analysis tooling** (2025-01-05):
  - `scripts/analyze_metrics.py` — comprehensive analysis with sensible defaults, plots
  - `scripts/load_test.py` — simulate concurrent users for worker experiments
- **Load test + metrics improvements** (2025-01-05):
  - Load test playback simulation mode (mirrors frontend buffering behavior)
  - Semaphore fix: jobs stay in Redis until worker ready, queue_depth accurate
  - New charts: synthesis_ratio (real-time factor), latency_breakdown (queue vs worker)
  - Model usage chart: server model breakdown + local/overflow split
  - Overflow threshold set to 8

**Pending work:**
None — core infrastructure complete.

**Deferred:**
- CLAUDE.md documentation — deferred until we know what's useful in practice

## Eviction Bug Fixes (2025-01-05 Investigation)

### Root Cause Analysis

**User observation:** After jumping 100 blocks ahead, ALL old blocks still complete processing (more than 2), causing slow buffering for the new position.

**Root causes found:**

1. **Unlimited concurrent tasks per worker** — `base.py` main loop:
   ```python
   while True:
       _, raw = await self._redis.brpop([self._queue], timeout=0)
       asyncio.create_task(self._handle_job(raw))  # No limit!
   ```
   If queue has 10 jobs, worker pops all 10 instantly and creates 10 concurrent asyncio tasks. All 10 check `is_pending` almost simultaneously, BEFORE cursor_moved eviction arrives.

2. **Silent skip on eviction** — When processor skips a job due to eviction (block not in pending set), it doesn't notify subscribers. This breaks the subscriber pattern when two blocks share the same variant_hash.

3. **Frontend cachedBlocksRef not cleared** — When `WSEvicted` message arrives, frontend clears `blockStatesRef` and `audioUrlsRef` but NOT `cachedBlocksRef`. Evicted blocks still show as 'cached' even though audio buffer is gone.

### Fixes Needed

**Fix 1: Backend semaphore** (`processors/tts/base.py`)
```python
async def run(self) -> None:
    await self.initialize()
    semaphore = asyncio.Semaphore(2)  # Max 2 concurrent jobs per worker

    async def process_with_limit(raw: bytes) -> None:
        async with semaphore:
            await self._handle_job(raw)

    while True:
        _, raw = await self._redis.brpop([self._queue], timeout=0)
        asyncio.create_task(process_with_limit(raw))
```
This ensures pending checks happen just-in-time: tasks wait at semaphore, so by the time they check `is_pending`, eviction has already happened.

**Fix 2: Notify subscribers on skip** (`processors/tts/base.py`)
```python
if not is_pending:
    logger.debug(f"Block {job.block_idx} evicted, skipping")
    await self._notify_subscribers(job.variant_hash, status="skipped")  # ADD THIS
    await self._redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))
    return
```
Frontend already treats "skipped" as 'pending' in derivation logic, so blocks can be re-requested.

**Fix 3: Frontend eviction handling** (`PlaybackPage.tsx`)
Fixed derivation logic to not show evicted blocks as 'cached' — check both `cachedBlocksRef` AND (`audioBuffersRef` OR `wsStatus === 'cached'`).

**Fix 4: Frontend cursor_moved on jump** (`PlaybackPage.tsx`)
**ROOT CAUSE OF MAIN BUG:** `handleBlockChange` (block jump) wasn't calling `ttsWS.moveCursor()`. Backend never knew when user jumped to a new position, so it never evicted old pending blocks.
```typescript
// In handleBlockChange, add:
if (documentId && isServerSideModel(voiceSelection.model)) {
  ttsWS.moveCursor(documentId, newBlock);
}
```

### Metrics Enhancements

**Add `block_idx` column** — For tracing specific blocks through the system. Currently in synthesis events we have document_id but not block_idx.

**Add `eviction_triggered` event** — When cursor_moved removes blocks from pending set:
```python
await log_event(
    "eviction_triggered",
    user_id=user.id,
    document_id=str(msg.document_id),
    data={
        "cursor": msg.cursor,
        "window": [min_idx, max_idx],
        "evicted_indices": to_evict,
        "evicted_count": len(to_evict),
    },
)
```

**Add `eviction_skipped` event** — When processor skips job due to eviction (in base.py).

### Other metrics enhancements discussed

- Track raw_text in synthesis events (currently only text_length)
- Billing verification: ensure cached blocks only billed once (can query cache_hit vs synthesis_complete events)

## Remaining Work Explained

### 1. Migrate stdlib logging to loguru
**COMPLETED** (2025-01-05) — All 11 modules migrated.

### 2. Request complete middleware
FastAPI middleware that logs every HTTP request completion:
```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    await log_event("request_complete",
        endpoint=request.url.path,
        method=request.method,
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000)
    )
    return response
```
Useful for: API latency monitoring, error rate by endpoint, identifying slow endpoints.

### 3. Document parse events
In `processors/document/manager.py` or the specific processors, log when document parsing completes:
```python
await log_event("document_parse",
    source_type="url",  # or "file", "text"
    block_count=len(blocks),
    total_chars=sum(len(b.text) for b in blocks),
    processing_time_ms=...,
    user_id=...,
)
```
Useful for: Understanding document processing load, OCR performance.

### 4. Eviction events for prefetch debugging
**INVESTIGATED** (2025-01-05) — Root cause found: unlimited concurrent tasks per worker. See "Eviction Bug Fixes" section above for full analysis and fixes.

### 5. Analysis tooling (NEEDS DISCUSSION)
What do we actually need? Options to discuss with user:
- Makefile targets for common queries?
- Python scripts for more complex analysis?
- Visualizations (charts, trends)?
- What specific queries are useful for day-to-day operations?

### 6. CLAUDE.md documentation (NEEDS DISCUSSION)
What should be documented?
- Where metrics DB lives
- How to query
- Event types reference
- Sample queries?

## Gotchas

- loguru uses `.exception()` instead of `exc_info=True` for tracebacks
- SQLite writer batches events every 5 seconds — not real-time but good enough for analysis
- stdlib logging and loguru can coexist — no need to migrate all modules immediately
- Metrics DB inside container at `/app/metrics/metrics.db`, must mount volume to access from host
- Workers (kokoro-cpu) are separate containers but synthesis processing runs in gateway via asyncio tasks

## Learnings from Using Metrics for Debugging (2025-01-05)

**Workflow that worked:**
1. User reported issue → checked metrics for relevant events
2. Query: `SELECT event_type, COUNT(*) FROM metrics_event GROUP BY event_type` — quick health check
3. Found zero `eviction_triggered` events during test → immediately knew eviction wasn't firing
4. Traced to frontend not calling `moveCursor` on block jump

**What helped:**
- Event-based logging (eviction_triggered, eviction_skipped) made gaps obvious
- SQLite timestamps made timeline reconstruction easy
- Having both event type and data JSON allowed flexible queries

**Since added (2025-01-05):**
- ✅ `block_idx` as a proper column — tracing specific blocks is now easy
- ✅ `synthesis_started` event — measures queue wait vs worker time

**Query patterns useful for debugging:**
```sql
-- Recent events timeline
SELECT datetime(timestamp, 'localtime'), event_type, data
FROM metrics_event ORDER BY timestamp DESC LIMIT 20;

-- Check for specific event types in time window
SELECT * FROM metrics_event
WHERE event_type = 'eviction_triggered'
AND timestamp > '2025-01-04T23:38:00';

-- Event counts for quick health check
SELECT event_type, COUNT(*) FROM metrics_event GROUP BY event_type;
```

## Analysis Tooling

**`scripts/analyze_metrics.py`** — Run with no args for comprehensive overview:
```bash
uv run scripts/analyze_metrics.py              # Last 24 hours, terminal output
uv run scripts/analyze_metrics.py --plot       # + matplotlib plots
uv run scripts/analyze_metrics.py --since "1 hour"  # Time filter
uv run scripts/analyze_metrics.py --model kokoro-cpu  # Filter by model
```

Shows:
- Event counts by type
- Latency stats by model (P50, P95 worker and total)
- Queue depth and wait time stats
- Eviction statistics
- Scatter plots: text_length vs latency (colored by time), latency over time
- Queue metrics over time

**`scripts/load_test.py`** — Simulate concurrent users:
```bash
uv run scripts/load_test.py                    # 5 users, 20 blocks each
uv run scripts/load_test.py --users 20 --blocks 50  # Heavy load
uv run scripts/load_test.py --token $(make token)   # If auto-auth fails
```

Workflow for worker experiments (2x8 vs 4x4 threads):
1. Start with config A: `make dev-cpu`
2. Run load test: `uv run scripts/load_test.py --users 10 --blocks 30`
3. Analyze: `uv run scripts/analyze_metrics.py --since "5 minutes" --plot`
4. Stop, change config, restart with config B
5. Repeat steps 2-3
6. Compare plots/stats

## Considered & Rejected

| Approach | Why Rejected |
|----------|--------------|
| JSON log files for trends | Too slow to query months of data |
| Periodic queue snapshots | Adds cron job complexity, event-based is cleaner |
| Hourly/daily aggregates only | Loses per-event detail, limits debugging |
| Prometheus/Grafana | GUI-based, not LLM-friendly, overkill for our scale |
| `log = logger` alias | Inconsistent pattern, using `logger` directly is cleaner |

## Handoff

Core metrics infrastructure complete. Interactive Streamlit dashboard added.

**To run:**
```bash
make dashboard        # Sync from prod + open interactive dashboard
make dashboard-local  # Use local metrics.db (from dev)
```

**Dashboard features:**
- Date range picker, model filters
- Summary stats: queue depth, overflow %, cache hit rate, usage by model
- Charts: synthesis scatter, ratio histogram with median, model usage, queue metrics
- Sync from prod button (dynamic container discovery for Docker Swarm)

**Recent commits:**
- `dfd0c87` — Initial Streamlit dashboard
- `380e69b` — Fixed legend colors, chart heights, added histogram distribution

**Known issues:**
- `queue_wait_ms` is NULL for all synthesis_complete events — latency breakdown chart shows no data. Backend fix needed in `processors/tts/base.py` to log this field.

**Semaphore explanation (for future reference):**
The semaphore (limit 2 concurrent jobs) IS intentional — it's what makes eviction work. Without it, all queued jobs check is_pending before eviction arrives. The fix for throughput is more workers (replicas), not higher semaphore.
