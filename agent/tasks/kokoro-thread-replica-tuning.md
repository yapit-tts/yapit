---
status: active
started: 2026-01-03
---

# Task: Kokoro Thread/Replica Tuning for Prod

Test T=8×2 vs T=4×4 on 16 vCPU:
- T=8×2 = lower latency per request
- T=4×4 = better load distribution

## Blocker

Depends on [[monitoring-observability-logging]] (legacy plan at `~/.claude/plans/monitoring-observability-logging.md`) — need to see actual latencies/queue depths to make data-driven decisions.

## Approach

1. Set up monitoring first
2. Test with automated script (can run on server):
   - Simulate 10 users at regular speed
   - 3 users at 2x speed
   - Check if any run into buffering
3. Compare metrics before/after config changes
4. Can also test manually with multiple browser tabs + monitoring dashboard
