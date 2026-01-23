# Metrics

Separate TimescaleDB instance for metrics (isolated from main Postgres).

## Architecture

- **Write path**: Gateway → asyncpg → TimescaleDB (batched every 5s)
- **Read path**: `make sync-metrics` exports to local DuckDB → `make dashboard`
- **Schema**: `docker/metrics-init.sql`
- **Code**: `yapit/gateway/metrics.py`

## Event Types

### TTS
- `synthesis_queued` — Job pushed to queue (queue_depth, queue_type)
- `synthesis_complete` — Worker finished (queue_wait_ms, worker_id, queue_type)
- `synthesis_error` — Synthesis failed

### Reliability
- `job_requeued` — Visibility timeout fired, job re-queued
- `job_dlq` — Job exceeded max retries, moved to dead letter queue

### Overflow
- `job_overflow` — Job sent to RunPod serverless
- `overflow_complete` / `overflow_error` — Serverless results

### Detection (YOLO)
- `detection_queued` — Detection job pushed (queue_depth)
- `detection_complete` / `detection_error` — Worker results (worker_id, processing_time)

### Extraction
- `extraction_estimate` — Pre-check token estimate before processing (estimated_tokens, num_pages, tolerance)
- `page_extraction_complete` — Gemini page extraction (all token counts)
- `page_extraction_error` — Extraction failed (status codes)

### Cache
- `document_cache_hit` — URL/upload cache hit
- `extraction_cache_hit` — All requested pages already cached
- `audio_cache_hit` — Variant already synthesized

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
2. Apply manually: `ssh prod 'docker exec $(docker ps -qf name=metrics-db) psql -U metrics -d metrics' < docker/metrics-migrations/NNN_description.sql`
3. Update init.sql to reflect current full schema (for fresh deploys)

During development: just nuke the volume (`docker volume rm yapit_metricsdata`) and redeploy.

## Dashboard

`dashboard/` module with modular structure:

- `tabs/` — Overview, TTS, Detection, Extraction, Reliability, Usage
- `theme.py` — Dark mode (GitHub-style colors)
- `data.py` — DuckDB queries
- `components.py` — Reusable chart components

```bash
make dashboard        # syncs from prod, then runs local dashboard
make dashboard-local  # runs dashboard on existing local data
make sync-metrics     # just sync, no dashboard
```

**Features:**
- Executive summary with KPIs and sparklines
- Per-worker and per-model breakdowns
- Gemini token cost calculation ($0.50/M input, $3.00/M output)
- Cache stats integrated into relevant sections
- Usage heatmap (hour × day) and user distribution

## Health Reports

Automated analysis via `make report`:

1. Syncs metrics (DuckDB) and logs from prod
2. Runs Claude with read-only tools to analyze system health
3. Reports to Discord (if `DISCORD_WEBHOOK_URL` set)
4. Saves full report to `~/tmp/yapit-reports/`

```bash
make sync-logs        # rsync + decompress logs from prod
make sync-data        # sync metrics + logs
make report           # full analysis
make report-post-deploy  # with deploy context
```

**Note:** Timeout values in the report prompt are hardcoded (TTS: 30s, YOLO: 10s). If changed in `yapit/gateway/__init__.py`, update `scripts/report.sh` too.

## Gotchas

- **Inworld `audio_duration_ms` is estimated** — Calculated from MP3 file size (~16KB/sec assumption), can be off 10-20%. Realtime ratio metrics for Inworld are approximate. Kokoro duration is accurate (calculated from PCM bytes). Frontend uses accurate duration from decoded AudioBuffer regardless.
- **Token counts are Gemini-specific** — `prompt_tokens`, `candidates_tokens`, `thoughts_tokens`, `total_tokens` columns only populated for Gemini extractions.
