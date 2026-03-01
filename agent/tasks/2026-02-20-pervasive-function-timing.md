---
status: backlog
refs: []
---

# Pervasive Function Timing

## Intent

We needed a full deploy cycle just to add timing instrumentation to `cache.store` — and only then discovered it was 42s p50. The data should already be there when something goes wrong.

A `@timed` decorator on I/O-boundary functions, always-on in production, feeding into the existing metrics pipeline. When any function starts misbehaving, the evidence is already in the database.

## Assumptions

- Per-call events don't scale. 100 users × 200 blocks × N instrumented functions = volume that dwarfs business events and overwhelms the 5s batch writer. Events must be aggregated in-process before flushing.
- In-process aggregation (one summary event per function per flush interval, with count/avg/p50/p95/max) makes volume O(functions × flush_rate), independent of traffic. 30 functions at 30s intervals = 1 event/s at any scale.
- The interesting signal is distribution stats (avg, p50, p95, max), not individual call traces. A jump in avg or p95 is how you spot a problem.
- Metrics DB is the right destination (not logs). Keeps everything in the same sync/query/dashboard workflow. 30-day raw retention is plenty for diagnosis.

## Research Needed

- Which functions to instrument — audit I/O boundaries across the codebase (cache, DB, Redis, HTTP, file I/O, external APIs). Not every function; not inner loops.
- Log level of JSON file output — if file logger is INFO, DEBUG-level decorator logs wouldn't appear. Need to verify `logging_config.py`.
- Flush interval tradeoff — shorter = faster anomaly visibility, longer = less volume. What's the right default?
- How the aggregation buffer interacts with async — multiple coroutines writing to the same buffer concurrently. Needs to be lock-free or use asyncio primitives.
- Whether existing metrics batching (5s asyncpg flush) needs adjustment to handle the new event type smoothly.
- Dashboard integration — a "slowest functions" panel, or just rely on ad-hoc DuckDB queries?

## Done When

- Decorator exists, is async-aware, aggregates in-process, flushes summaries to metrics DB.
- Applied to I/O-boundary functions across the codebase.
- Volume is scale-independent (verified under burst).
- Queryable: "show me the slowest functions in the last hour" works via standard metrics workflow.
