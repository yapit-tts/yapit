# Metrics

Separate TimescaleDB instance for metrics (isolated from main Postgres).

## Architecture

- **Write path**: Gateway → asyncpg → TimescaleDB (batched every 5s)
- **Read path**: `make sync-metrics` exports to local DuckDB → `make dashboard`
- **Schema**: `docker/metrics-init.sql`
- **Code**: `yapit/gateway/metrics.py`

### Writer self-healing (2026-08)

The writer survives an unreachable metrics DB (startup or mid-life): events buffer in a bounded deque (10k, oldest dropped first) and every tick retries connect/write with backoff (5s→60s). ERROR logged on outage start + every 10 min while down; on recovery an INFO log plus a `warning` metrics event (`Metrics DB outage recovered`, with outage duration and drop count) land in the DB itself.

Why this exists: Swarm deploys race the gateway (`update_config: start-first`) against metrics-db (`stop-first`, required — single Postgres volume). A gateway task can come up seconds before the metrics-db task's DNS name resolves. The pre-2026-08 writer gave up permanently on that first failure — a 5-day silent metrics blackout (2026-08-07 → 08-12). Swarm has no `depends_on`, so the race itself stays; the self-healing client is the fix. Liveness: the writer writes a `heartbeat` event whenever an hour passes without any other write, so a live pipeline never leaves a gap longer than an hour in `metrics_event`; `scripts/metrics_freshness.py` (run by `report.sh`) turns a longer gap into a deterministic STALE verdict.

## Event Types

### TTS
- `synthesis_queued` — Job pushed to queue (queue_depth, queue_type)
- `synthesis_complete` — Worker finished (queue_wait_ms, worker_id, queue_type)
- `synthesis_error` — Synthesis failed

### Reliability
- `job_requeued` — Visibility timeout fired, job re-queued
- `job_dlq` — Job exceeded max retries, moved to dead letter queue

### Liveness
- `heartbeat` — Written by the metrics writer after an hour without any other write (and on start). No other fields; the freshness check's only input.

### Detection (YOLO)
- `detection_queued` — Detection job pushed (queue_depth)
- `detection_complete` / `detection_error` — Worker results (worker_id, processing_time)

### Document Extraction
- `document_extraction_complete` — Emitted for every document extraction (all paths). `processor_slug` identifies the method: `pymupdf`, `epub`, `passthrough`, `defuddle:static`, `defuddle:static-bot`, `defuddle:playwright`, `gemini`. Has `duration_ms` (top-level column), `data.chars`, `data.images`, `data.pages`.
- `document_extraction_error` — Extraction failed. `processor_slug`, `data.error`, `data.content_type`.
- `extraction_estimate` — Pre-check token estimate before processing (estimated_tokens, num_pages, tolerance)
- `page_extraction_complete` — Per-page Gemini extraction (all token counts + `cached_content_token_count` for prompt cache utilization)
- `page_extraction_error` — Gemini page extraction failed (status codes)
- `figure_count_mismatch` — YOLO detected N figures but Gemini output M placeholders (page_idx, yolo_count, gemini_count, delta, content_hash)

### Cache
- `document_cache_hit` — URL/upload cache hit
- `extraction_cache_hit` — All requested pages already cached
- `cache_hit` — Variant already synthesized (audio cache)

### URL Fetching
- `url_fetch` — HTTP download (duration_ms, content_type, size_bytes, errors)
- `markxiv_error` — arXiv extraction failures

### WebSocket
- `ws_connect` / `ws_disconnect` — Connection lifecycle

### Batch
- `batch_job_submitted` / `batch_job_complete` / `batch_job_failed` — Gemini batch extraction lifecycle

### Billing
- `stripe_webhook` — Stripe webhook processing (duration_ms, event_type, errors)
- `billing_sync_drift` — Background sync detected drift from Stripe
- `billing_processed` — TTS billing consumer batch (duration_ms, text_length, data.events_count, data.users_count). Reconcile count(synthesis_complete) vs sum(data.events_count) to detect lost billing events.

### Rate Limiting
- `api_rate_limit` — External API returned 429 (status_code, retry_count, data.api_name). Emitted before retry from API adapters.

## Retention & Aggregates

| Data | Retention |
|------|-----------|
| Raw events (`metrics_event`) | 30 days |
| Hourly aggregates (`metrics_hourly`) | 1 year |
| Daily aggregates (`metrics_daily`) | Forever |

Compression kicks in at 7 days (segmented by event_type, model_slug).

## Schema Migrations

init.sql only runs on first container start. For existing databases:

1. Write migration in `docker/metrics-migrations/NNN_description.sql`
2. Apply manually — **the `-i` flag on `docker exec` is required** for stdin piping:
   ```
   cat docker/metrics-migrations/NNN.sql | ssh yapit-prod 'docker exec -i $(docker ps -qf name=metrics-db) psql -U metrics -d metrics'
   ```
   Without `-i`, docker exec doesn't attach stdin — psql sees EOF and exits silently with no error, no SQL executed.
3. Update init.sql to reflect current full schema (for fresh deploys)

During development: just nuke the volume (`docker volume rm yapit_metricsdata`) and redeploy.

## Dashboard

`dashboard/` module with modular structure:

- `tabs/` — Overview, TTS, Documents (unified: detection + extraction + batch), Reliability, Usage
- `theme.py` — Dark mode (GitHub-style colors)
- `data.py` — DuckDB queries
- `components.py` — Reusable chart components

```bash
make dashboard        # syncs from prod, then runs local dashboard
make dashboard-local  # runs dashboard on existing local data
make sync-metrics     # just sync, no dashboard
```

**Features:**
- Executive summary with KPIs and sparklines, always-visible Trends section using daily aggregates
- Per-worker and per-model breakdowns
- Gemini token cost calculation ($0.50/M input, $3.00/M output)
- Cache stats integrated into relevant sections
- Usage heatmap (hour × day) and user distribution
- User Type filter (All/Guest/Registered) — segments raw metrics events by `anon-` prefix
- Date range: quick toggles (7d/14d/30d) replace calendar picker

## Health Reports

Automated analysis via `make report`:

1. Syncs metrics (DuckDB) and logs from prod
2. Runs the deterministic freshness check (`scripts/metrics_freshness.py`) — a STALE verdict is injected as the first context section so the agent leads with it
3. Runs Claude with read-only tools to analyze system health
4. Saves the full report to `~/logs/yapit-reports/` and records the run in `~/logs/runs/yapit-health-report.jsonl`
5. Notifies (email, via the dotfiles `alert-send`) only when the report opened with ⚠️ issues, or when its status line could not be read at all — a green day and an anomaly note are read from the laptop's yapit dashboard instead. `scripts/report.sh --classify < report.md` prints the verdict that decides this.

```bash
make sync-logs        # rsync + decompress logs from prod
make sync-data        # sync metrics + logs
make report           # full analysis
make report-post-deploy  # with deploy context
```

**Note:** The visibility timeout values in the report prompt are a copy of the constants in `yapit/gateway/__init__.py` — when changing them, update `scripts/report.sh` in the same commit.

## Gotchas

- **Token counts are Gemini-specific** — `prompt_tokens`, `candidates_tokens`, `thoughts_tokens`, `cached_content_token_count`, `total_tokens` columns only populated for Gemini extractions.
- **Schema design: columns vs JSONB `data`** — Dedicated columns for fields that need aggregation (token counts, latencies, queue depths — used in continuous aggregates and dashboard queries). JSONB `data` field for ad-hoc context (error messages, content hashes, job IDs). When adding a new field, ask: "will this be aggregated/trended?" → column. "Just extra context for debugging?" → `data`.
