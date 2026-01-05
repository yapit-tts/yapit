---
status: active
started: 2026-01-03
priority: low
---

# Task: Model-Specific Block Chunking

## Idea

Different TTS models may benefit from different chunk sizes:
- Kokoro (local/server): small blocks (~200 chars) for fast time-to-first-audio
- Inworld API: larger blocks (up to 500k chars) — API handles internal coherence via decoder context extension

Store multiple block versions per document, switch based on selected model.

## Why This Might Matter

Inworld API maintains chunk-to-chunk consistency within a single streaming request. Larger chunks could yield better voice coherence than our current small-block approach. Needs testing.

## Architecture

- Store multiple block sets per document (one per chunking strategy)
- When switching models, reload blocks with optimal chunking for that model
- Position resets to start on model switch (simpler than mapping positions between different block structures)
- Separate audio cache per block version (cache miss on switch, that's fine)

## What Needs Testing

1. **Quality**: Does larger chunking actually improve voice coherence noticeably?
2. **Latency**: Do larger chunks stay real-time enough? Or does time-to-first-audio suffer / cause buffering?

## Status

Needs exploratory benchmarking first.

Low priority, but if testing shows marked improvement, consider implementing before public launch rather than after (easier to do while architecture is still flexible).

## Related

- [[inworld-api-evaluation]] — API capabilities, rate limits, coherence behavior
