---
status: active
refs: []
---

# Move cache.store Off the Hot Path

## Intent

The result consumer's `_handle_success` serializes through a single aiosqlite writer for `cache.store` (REPLACE INTO + COMMIT = fsync). Under burst from GPU workers, 40 concurrent tasks contend for this single writer, causing finalize times of 14-82 seconds — all before the user gets their audio.

The hot/cold billing split (978d5ee) removed Postgres from the hot path but cache.store remains the bottleneck. Timing instrumentation added in this deploy (`synthesis_complete.data.cache_store_ms`) will provide hard data.

Proposed architecture: store audio in Redis first (SET with short TTL, sub-ms), notify client immediately, persist to SQLite in a background task. The `/v1/audio/{hash}` endpoint checks Redis first, falls back to SQLite.

## Assumptions

- `cache_store_ms` timing will confirm SQLite fsync is the dominant cost (vs CPU starvation from co-located workers or disk I/O amplification). If the numbers show cache.store is fast and the stall is elsewhere, the fix is different.
- Redis can hold burst audio temporarily. 40 blocks × ~100KB each = ~4MB. Trivial.
- Audio TTL in Redis can be short (60-120s) — just long enough for the client to fetch it and for SQLite persistence to catch up.

## Done When

- Timing data from prod confirms cache.store is the bottleneck
- Hot path is: Redis SET → notify → billing push (zero SQLite)
- `/v1/audio/{hash}` reads Redis first, falls back to SQLite
- Background task persists Redis → SQLite
- Stress test shows sub-second finalize times under burst
