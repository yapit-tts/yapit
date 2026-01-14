---
status: active
started: 2026-01-13
---

# Task: Monitoring, Alerting & Automated Analysis

Pre-launch observability work. We have data collection (TimescaleDB + logs), now need actionable monitoring.

## Intent

Don't discover issues when users complain. Have automated checks, alerts, and periodic analysis.

## Work Items

### 1. Simple Alerts (ntfy.sh)

Thresholds to alert on:
- Error rate > X% (TBD, start conservative)
- Queue depth > 30
- Disk usage > 80%
- Container unhealthy

Implementation: Hook into existing metrics, POST to ntfy topic when threshold crossed.
Public topics fine for non-sensitive alerts.

### 2. Metrics Coverage Gaps

Currently synthesis-focused. Add:
- [ ] Auth failures (promote from DEBUG, log to metrics)
- [ ] HTTP request latencies (general, not just synthesis)
- [ ] Billing/Stripe events (webhook activity, failures)
- [ ] Document processing events (parallel task may cover this)
- [ ] Playwright usage (how often fallback to browser fetch is needed)

### 3. Infra Metrics

Hetzner exposes some via their dashboard. Question: worth pulling into our stack for unified view, or just use Hetzner dashboard separately?

Options:
- Node-exporter + Prometheus → more infra to manage
- Just use Hetzner dashboard → simpler, good enough for side project scale
- Hybrid: only pull what we need (disk usage for alerts)

### 4. Agent-in-a-Loop Automated Analysis

Daily (or every few hours) automated health check:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Cron/systemd│───▶│ Sync script │───▶│ Claude      │───▶ Discord webhook
│ timer       │    │ (metrics +  │    │ (analyze,   │    (if issues found)
└─────────────┘    │  logs)      │    │  report)    │
                   └─────────────┘    └─────────────┘
```

Design decisions:
- **Pre-fetch data locally** — Claude doesn't need tool calls for basic analysis
- **Allow tool calls optionally** — if deeper digging needed
- **Run in sandbox mode** — safe to give full permissions on local copy
- **Model choice** — Sonnet for cost, Opus if prompts need more intelligence
- **Output** — Private Discord webhook, always fires (✓ nominal / ⚠ issues found). No message = script broken.

Sync mechanism:
- Metrics: `make sync-metrics` already exists (→ DuckDB)
- Logs: need `make sync-logs` (copy log files locally)

### 5. Log Sync Mechanism

Add `make sync-logs` similar to `make sync-metrics`:
- Copy `/data/gateway/logs/*.jsonl*` from prod
- Store in `gateway-data/logs/`
- Analysis can then run locally with full permissions

## Access Pattern Summary

| Data | Prod Location | Local Sync | Analysis |
|------|---------------|------------|----------|
| Metrics | TimescaleDB | `make sync-metrics` → DuckDB | SQL queries |
| Logs | `/data/gateway/logs/` | `make sync-logs` → local files | jq, Claude |

Both give full local access without endangering prod. Good for sandbox mode.

## Open Questions

- Exact thresholds for alerts (start conservative, tune over time)
- Frequency for agent-in-loop (daily? every 6h? cost vs value)
- Hetzner infra metrics: consolidate or keep separate?

## Sources

- [[metrics]] — TimescaleDB setup, retention policies
- [[logging]] — loguru config, JSON format

