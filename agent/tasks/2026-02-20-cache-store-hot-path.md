---
status: active
refs: []
---

# Move cache.store Off the Hot Path

## Intent

The result consumer's `_handle_success` serializes through a single aiosqlite writer for `cache.store` (REPLACE INTO + COMMIT = fsync). Under burst from GPU workers, 40 concurrent tasks contend for this single writer, causing finalize times of 14-82 seconds — all before the user gets their audio.

Root cause: serialized fsync. Each `cache.store()` does REPLACE INTO + COMMIT. COMMIT triggers fsync. 40 concurrent tasks → 40 serial fsyncs through one aiosqlite writer. Each task waits for all preceding fsyncs. With VPS disk latency (5-300ms per fsync under I/O load), tail latency reaches 40-80s.

Fix: Redis as fast buffer (SET, sub-ms) → notify immediately → batch-persist to SQLite in background. Batching is the throughput fix: one transaction wrapping N inserts = one fsync instead of N. Same drain-on-wake pattern as the billing consumer.

Also: delete `BlockVariant.cache_ref` — it's redundant with the primary key (`variant_hash`), never read functionally.

## Assumptions

- ~~`cache_store_ms` timing will confirm SQLite fsync is the dominant cost~~ **Confirmed.** Stress test data (180 events, 1-5 concurrent users): cache_store avg=42s, p50=45s, p95=74s. notify avg=18ms, overhead avg=5ms. cache.store accounts for 99.9% of finalize time.
- Redis can hold burst audio temporarily. 40 blocks × ~100KB each = ~4MB. Trivial.
- Audio TTL in Redis of 300s gives plenty of margin for client fetch + batch persist.
- SQLite single writer is fine — the persister IS the only writer. No contention.

## Done When

- [x] Timing data from prod confirms cache.store is the bottleneck
- Hot path is: Redis SET → notify → billing push (zero SQLite)
- `/v1/audio/{hash}` reads Redis first, falls back to SQLite
- Background persister: drain-on-wake, batched SQLite writes (one fsync per batch)
- `cache_ref` column deleted from BlockVariant
- Stress test shows sub-second finalize times under burst

## Considered & Rejected

- **In-memory buffer instead of Redis**: Simpler but loses audio on gateway crash. Redis is already in the stack, crash resilient, zero cost.
- **Fire-and-forget cache.store() (non-blocking)**: Same 40 serial fsyncs, same throughput problem, just non-blocking. Under sustained load, persister falls behind indefinitely.
- **One-at-a-time persister (no batching)**: Same throughput issue. ~1 write/s vs ~200+ writes/s with batching.
