---
status: done
type: research
---

# Task: User Stats & Analytics

Related: [[monitoring-observability-logging]] — structured logging, metrics infrastructure

## Goal

Design stats/analytics approach for:
1. User profile page (total audio synthesized, documents processed, etc.)

voice usage (self)
voice usage (all, public voices)

## Context

Subscription refactor removed `UserUsageStats` table (pre-aggregated totals). Now using `UsageLog` as single source of truth for billing events.

## Open Questions

- Aggregate on-demand from UsageLog, or maintain separate stats table?
- Where do operational metrics (cache hits/misses) live? Prometheus? Loguru JSON logs?
- What stats do we actually want to show users?

## Ideas

- **User-facing stats**: Total hours synthesized, documents created, characters processed — can derive from UsageLog
- **Operational metrics**: Cache hit/miss rates, synthesis latency percentiles — better suited for structured logging + metrics system (see [[monitoring-observability-logging]])
