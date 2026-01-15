
# Metrics

Separate TimescaleDB instance for metrics (isolated from main Postgres).

## Architecture

- **Write path**: Gateway → asyncpg → TimescaleDB (batched every 5s)
- **Read path**: `make sync-metrics` exports to local DuckDB → `make dashboard`
- **Schema**: `docker/metrics-init.sql`
- **Code**: `yapit/gateway/metrics.py`

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

```bash
make dashboard        # syncs from prod, then runs local dashboard
make dashboard-local  # runs dashboard on existing local data
make sync-metrics     # just sync, no dashboard
```

## Gotchas

- **Inworld `audio_duration_ms` is estimated** — Inworld calculates duration from MP3 file size (~16KB/sec assumption), can be off 10-20%. Realtime ratio metrics for Inworld are approximate. Kokoro duration is accurate (calculated from PCM bytes). Frontend uses accurate duration from decoded AudioBuffer regardless.

