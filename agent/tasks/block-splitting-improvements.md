---
status: active
started: 2026-01-03
---

# Task: Block Splitting Improvements

Current issue: sometimes sentences are split audibly unnaturally.

## Approach

1. **First**: Improve splitting logic
   - Better to split at "," in addition to "?!."
   - Preferred split points > reaching exact limit
   - Soft limit with preferred split points

2. **Then**: Try increasing block size (200 or 250)
   - Check: does this increase latency or introduce buffering?
   - Probably fine due to markdown structure for most documents

## After Block Size Change

Test with functioning WebGPU devices to verify:
- Reasonable loading times
- No buffering issues

## Monitoring

Monitor latencies before/after changes. Depends on [[monitoring-observability-logging]] for data-driven validation.
