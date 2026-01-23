---
status: done
started: 2026-01-13
completed: 2026-01-23
---

# Task: Monitoring, Alerting & Automated Analysis

Pre-launch observability work. We have data collection (TimescaleDB + logs), now need actionable monitoring.

## Intent

Don't discover issues when users complain. Have automated checks, alerts, and periodic analysis.

## Work Items

### 1. Simple Alerts (ntfy.sh) — ✅ Superseded

**Superseded by agent-in-loop (section 4).** The daily report agent already surfaces errors, queue issues, and anomalies via Discord webhook. Adding separate ntfy threshold alerts would be redundant complexity.

Deploy notifications already use ntfy (`.github/workflows/deploy.yml` → `ntfy.sh/yapit-tts-deploy`). Runtime alerting is handled by the daily agent.

### 2. Metrics Coverage Gaps

Currently synthesis-focused. For each area, consider:

**Prio 1 — LLM-analyzable diagnostics:**
What can be queried from SQL/logs and interpreted by automated agents?
- Error patterns, anomaly detection, issue diagnosis
- Should be straightforward: raw data + aggregates → LLM → insight

**Prio 2 — Human dashboard / cross-cutting insights:**
Higher-level stuff LLMs might struggle with, but humans benefit from at a glance.
- Per-model breakdowns (synthesis ratio, queue depth, wait time — currently missing)
- Buffer health: are blocks actually buffering? (needs frontend+backend algorithm awareness)
- Time-to-first-audio (real user experience metric)
- Dashboard needs overhaul: more informative at first glance, visual polish, better labeling

**Prio 3 — Cool stats / other:**
- Voice popularity
- Peak usage patterns
- Document complexity vs processing time correlations
- Cost tracking (external API calls: Gemini, RunPod, etc.)

Areas to cover:
- [x] ~~Auth failures~~ — decided against (expired tokens are normal, too noisy)
- [x] ~~HTTP request latencies (general)~~ — deferred, low value (TTS/extraction latencies already tracked, general endpoint latency rarely the issue)
- [x] Billing/Stripe events — `stripe_webhook` with duration_ms, event_type, errors (7aca6ea)
- [x] Document processing events — `url_fetch` with duration/content_type/errors, `content_hash` added to extraction events for estimate correlation (7aca6ea)
  - Gemini API: success/failure rates, retry counts, error types (429/500/503/504), pages processed vs failed
- [x] Playwright usage — `playwright_fetch` with duration_ms (7aca6ea)
- [x] ~~External API usage~~ — deferred, billing consoles more accurate + dashboard already shows usage
- [x] ~~User session metrics~~ — out of scope, product analytics territory (PostHog/Plausible better fit)

### 3. Infra Metrics

Hetzner exposes some via their dashboard. Question: worth pulling into our stack for unified view, or just use Hetzner dashboard separately?

Options:
- Node-exporter + Prometheus → more infra to manage
- Just use Hetzner dashboard → simpler, good enough for side project scale
- Hybrid: only pull what we need (disk usage for alerts)

### 4. Agent-in-a-Loop Automated Analysis ✅

Implemented in 5cc550b (`scripts/report.sh`, `make report`). See [[metrics]] for usage.

Daily (or every few hours) automated health check:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Cron/systemd│───▶│ Sync script │───▶│ Claude      │───▶ Discord webhook
│ timer       │    │ (metrics +  │    │ (analyze,   │    (if issues found)
└─────────────┘    │  logs)      │    │  report)    │
                   └─────────────┘    └─────────────┘
```

Design decisions:
- **Sync data first** — metrics to DuckDB, logs decompressed locally
- **Targeted allowedTools** — read-only: jq, grep, cat, head, tail, duckdb, etc.
- **Run on laptop** — systemd user timer at 22:00 daily
- **Output** — Discord webhook + saved to `~/tmp/yapit-reports/`
- **Post-deploy variant** — `make report-post-deploy` or `--after-deploy` flag

Note: Timeout values (TTS: 30s, YOLO: 10s) hardcoded in prompt — update if changed in code.

### 5. Log Sync Mechanism ✅

Implemented alongside agent-in-loop:
- `make sync-logs` — rsync from Docker volume, auto-decompress .gz files
- `make sync-data` — sync both metrics + logs
- Logs at: `/var/lib/docker/volumes/yapit_gateway-data/_data/logs/` on prod

## Access Pattern Summary

| Data | Prod Location | Local Sync | Analysis |
|------|---------------|------------|----------|
| Metrics | TimescaleDB | `make sync-metrics` → DuckDB | SQL queries |
| Logs | Docker volume `yapit_gateway-data` | `make sync-logs` → `gateway-data/logs/` | jq, Claude |

Both give full local access without endangering prod.

### 6. Stress Testing → Extracted to [[stress-testing]]

## Open Questions

- Exact thresholds for alerts (start conservative, tune over time)
- ~~Frequency for agent-in-loop~~ → Daily at 10pm via systemd timer
- Hetzner infra metrics: consolidate or keep separate?

## Sources

- [[metrics]] — TimescaleDB setup, retention policies
- [[logging]] — loguru config, JSON format

