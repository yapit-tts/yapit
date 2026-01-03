---
status: active
started: 2025-01-02
---

# Task: Operational Metrics & Visibility

Related: [[monitoring-observability-logging]] — structured logging infrastructure (legacy plans)

## Intent

Need visibility into system health to answer capacity planning questions:
- Is performance consistent? Are users experiencing buffering?
- Do we need more cores? Faster cores? RunPod overflow?
- What's consuming storage?

Want some kind of report — could be CLI tool, could be proper monitoring (Prometheus/Grafana), could be Claude-synthesized from logs. Nice visualization is a bonus but not required.

### What to See

**Storage stats:**
- Audio cache size
- Document cache size
- DB total size
- Per-table DB breakdown (expensive, on-demand only)

**Queue & performance:**
- Queue length — how much backlog
- Average wait time — time requests sit in queue before processing
- Time to first synthesis — latency from request to first audio chunk
- Whether requests finish before client starts buffering

### Why

Diagnose bottlenecks and make infrastructure decisions:
- High queue + high wait time → need more cores
- Low queue but slow synthesis → need faster cores
- Sustained queue buildup → consider RunPod overflow

## Sources

- [[monitoring-observability-logging]] — existing logging decisions, loguru setup plan — MUST READ

## Considered & Rejected

(none yet)

## Handoff

Requirements captured. Next: decide approach (enhance logging vs Prometheus vs hybrid).
