---
status: active
started: 2026-01-03
---

# Task: Block Splitting Improvements

Current issue: sometimes sentences are split audibly unnaturally.

## Test Data

Real-world test excerpt: `splitter-improvement-sample-text.txt` (root directory)

## Problem Example

```
"When we look carefully at the quiescent period in the bff soup before tapes begin replicating, we notice a steady rise in the amount of computation [SPLIT] taking place."
```

Split happens mid-sentence where it could easily have included a few more words. These bad splits hurt naturalness and voice consistency.

## Goal

Keep sentences whole when possible. When splitting is necessary, prefer natural pause points:
- Sentence enders: `.?!`
- Clause separators: `,` `—` (m-dash) `:`
- Avoid splitting mid-phrase when just a few more words would complete it

A block being slightly longer or shorter is fine — what matters is sounding natural.

## Approach

1. **First**: Improve splitting logic
   - Soft limit with preferred split points
   - Prefer natural pause punctuation over hard cutoff
   - A few extra words to finish a sentence > exact character limit

2. **Then**: Try increasing block size (200 or 250)
   - Check: does this increase latency or introduce buffering?
   - Probably fine due to markdown structure for most documents

## After Block Size Change

Test with functioning WebGPU devices to verify:
- Reasonable loading times
- No buffering issues

## Monitoring

Monitor latencies before/after changes. Depends on [[monitoring-observability-logging]] for data-driven validation.
