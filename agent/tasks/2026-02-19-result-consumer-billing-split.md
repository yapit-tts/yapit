---
status: active
refs: []
---

# Split Result Consumer: Hot Path / Cold Path

## Intent

The result consumer processes worker results in a single function that mixes user-facing work (cache audio, notify WebSocket) with internal bookkeeping (Postgres: billing, engagement stats, BlockVariant metadata). Under burst from fast GPU workers, the Postgres operations exhaust the shared connection pool and block the WebSocket request path from queuing new synthesis jobs.

Root cause: `record_usage` acquires a FOR UPDATE row lock per result. With 40 concurrent `_handle_success` tasks each holding a connection while waiting for the lock, the pool (30 connections) is fully occupied. The gateway can't process new `synthesize` WebSocket requests until billing tasks release their connections.

Fix: split into two consumers with complete resource isolation.

- **Result consumer (hot path):** cache.store → notify subscribers → push billing event to `tts:billing` Redis list. Zero Postgres. User sees their audio here.
- **Billing consumer (cold path):** pops from `tts:billing`, updates BlockVariant, records usage, upserts engagement stats. Own connection pool (2 connections). Serial processing eliminates FOR UPDATE contention between TTS billing tasks.

New metric event `billing_processed` tracks cold path health (processing time per event). Billing queue depth (`LLEN tts:billing`) is the primary health signal.

## Assumptions

- The billing batch window (seconds) is small enough that `check_usage_limit` seeing stale usage is acceptable. Max exploitation during window is bounded by rate limits × chars per block — pennies for TTS.
- `record_usage` with FOR UPDATE is still needed for correctness against concurrent OCR billing / Stripe webhook writes to the same subscription row. But with serial TTS billing, lock contention is minimal (1 connection vs 30).
- Redis persistence (RDB/AOF) makes `tts:billing` more durable than the current approach (events lost on gateway crash between notify and Postgres commit).

## Done When

- [x] Result consumer rewritten — no Postgres imports, no settings dependency
- [x] Billing consumer running on own connection pool
- [x] Billing consumer batched: drain-on-wake collection, per-user transactions via `record_usage(commit=False)`
- [x] `billing_processed` metric event logged per batch (events_count, users_count, duration_ms, text_length)
- [x] Dashboard updated with billing consumer section (reconciliation delta, processing time chart)
- [x] Monitoring agent (`scripts/report.sh`) updated: billing_processed event docs, reconciliation check, liveness check
- [x] Knowledge files updated: [[tts-flow]] (split architecture), [[metrics]] (billing_processed event)
- [ ] Stress test validates: no pool starvation at 5+ users with GPU workers

## Considered & Rejected

- **Semaphore on Postgres phase** — Caps concurrent billing connections but doesn't isolate pools. A burst can still degrade request latency if semaphore limit is too high. Band-aid.
- **Remove FOR UPDATE entirely** — Works for kokoro (atomic SQL increment), but premium voice waterfall billing (subscription → rollover → purchased) is a read-modify-write that needs atomicity. Keeping FOR UPDATE with serial processing is correct and simple.
- **Batch billing in single transaction** — `record_usage` commits internally; changing that touches other callers (OCR billing). Serial one-at-a-time processing with the existing `record_usage` is correct, simple, and fast enough (one connection, no contention). Can add batching later if needed.
- **Reservation layer for TTS billing** — Adds Redis counters to prevent usage limit bypass during billing delay. Max exploit is pennies for TTS (unlike OCR where a single PDF can cost dollars). Not worth the complexity now; architecture supports bolting it on later.
