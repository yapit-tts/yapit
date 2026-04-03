# TTS Flow

How text becomes audio in Yapit. The core synthesis pipeline from document blocks to playable audio.

## Overview

```
Document → Blocks → WebSocket → Queue/Cache check → Worker pulls → Synthesis → Result consumer → Cache → Notify
```

How documents become blocks: see [[document-processing]].

**Key insight:** Audio is cached by content hash (`variant_hash`), not by document/block. Same text + model + voice = same audio, shared across users and documents.

## The Pipeline

### 1. Document → Blocks

Markdown processing creates speakable blocks with `audio_block_idx`:

- `yapit/gateway/markdown/parser.py` — Parse markdown AST
- `yapit/gateway/markdown/transformer.py` — Assign audio indices, split long blocks
- `yapit/gateway/markdown/models.py` — StructuredDocument schema

Blocks with audio: heading, paragraph, list, blockquote. No audio: code, math, table, image, hr.

Block splitting: Markdown structure → paragraphs → sentences → clauses → word boundaries. See `TextSplitter` in transformer.

### 2. WebSocket Protocol

Frontend connects via WebSocket for real-time synthesis control:

- `yapit/gateway/api/v1/ws.py` — WebSocket endpoint, synthesis orchestration
- `yapit/contracts.py` — Job/result types (SynthesisJob, WorkerResult)

**Messages:**

| Direction | Type | Purpose |
|-----------|------|---------|
| Client→Server | `synthesize` | Request synthesis for block indices |
| Client→Server | `cursor_moved` | Evict blocks outside playback window |
| Server→Client | `status` | Per-block status update (queued/processing/cached/error/skipped). Includes `recoverable` bool — `false` only for session-level errors (usage limit). Playback engine advances past recoverable errors. |
| Server→Client | `evicted` | Blocks evicted after cursor move |
| Server→Client | `error` | Document-level errors (not found, invalid model) |

**Cursor-aware eviction:** When cursor moves (`cursor_moved` message), backend evicts ALL pending blocks — clean slate. The frontend is the sole authority on what blocks to synthesize; the next `synthesize` message fills the queue fresh. Uses sorted set for O(log N) eviction.

### 3. Deduplication

Before queuing, check if variant already exists:

```
variant_hash = hash(text | model_slug | voice_slug | sorted key=value pairs from voice.parameters)
```

- If cached → return audio URL immediately
- If in-flight → subscribe to existing job
- Otherwise → create job, queue it

See `BlockVariant.get_hash()` in `domain_models.py` and `request_synthesis()` in `gateway/synthesis.py`.

### 4. Worker Architecture

Pull-based workers instead of HTTP-based. Workers pull jobs from Redis, gateway only pushes jobs and consumes results.

**Queue structure:**
- `tts:queue:{model}` — Sorted set with job_id as member, timestamp as score
- `tts:jobs` — Hash mapping job_id to job JSON
- `tts:job_index` — Hash mapping "user:doc:block" to job_id (for eviction)
- `tts:results` — List for completed results

**Workers:**
- `yapit/workers/tts_loop.py` — TTS worker loop with two modes:
  - `run_tts_worker` — Sequential processing for GPU models (Kokoro). One job at a time, visibility tracking for retries.
  - `run_api_tts_dispatcher` — Parallel processing for API models (Inworld, OpenAI TTS). Spawns task per job, unlimited concurrency. No visibility tracking (if gateway crashes, in-flight jobs lost).
- `yapit/workers/adapters/kokoro.py` — Kokoro adapter (local model)
- `yapit/workers/adapters/inworld.py` — Inworld adapter (API calls, with retry logic for 429/500/503/504)
- `yapit/workers/adapters/openai_tts.py` — OpenAI-compatible adapter (any `/v1/audio/speech` endpoint). Requests `opus` format, detects OGG Opus via magic bytes (pass-through), transcodes other formats to OGG Opus via PyAV. Same retry logic as Inworld.

Workers only need Redis access. No Postgres, no HTTP endpoints. Gateway handles all DB writes and notifications centrally.

**Why pull-based:**
- Natural load balancing (faster workers pull more)
- Any device can be a worker (home GPU, VPS, cloud)
- Zero gateway changes to add/remove workers

### 5. Result Processing (Hot/Cold/Persist Split)

Three consumers with complete resource isolation:

**Result consumer (hot path)** — `yapit/gateway/result_consumer.py`

Pops from `tts:results`, spawns a task per result. No Postgres, no SQLite.
1. Atomically claim result (inflight key dedup)
2. Redis SET audio (`tts:audio:{hash}`, 300s TTL) — sub-ms
3. Notify subscribers via Redis pubsub (user sees audio here)
4. XADD `BillingEvent` to `tts:billing:stream` (Redis Stream)
5. Push variant_hash to `tts:persist` for background SQLite persistence

**Cache persister** — `yapit/gateway/cache_persister.py`

Drain-on-wake from `tts:persist` (same pattern as billing consumer). MGET audio from Redis, batch-write to SQLite in one transaction (one COMMIT = one fsync for the whole batch). Turns 40 fsyncs into 1.

**Billing consumer (cold path)** — `yapit/gateway/billing_consumer.py`

Redis Streams consumer group on `tts:billing:stream`. At-least-once delivery: events stay pending until XACK after Postgres commit. Own Postgres connection pool (2 connections), isolated from request path.
1. On startup: create consumer group (idempotent), recover unacked events from previous crashes
2. XREADGROUP to collect batches (block 5s, up to 200)
3. Update BlockVariant metadata (duration_ms) — one transaction for batch
4. Per-user transaction: `record_usage()` with idempotency via `event_id` (dedup on `UsageLog.event_id` UNIQUE constraint, keyed on `job_id`), then upsert `UserVoiceStats` only if not a duplicate
5. XACK + XDEL after Postgres commit

**Why three paths:** Fast GPU workers can dump 40+ results in seconds. The hot path must be sub-ms so users get audio immediately. SQLite's single writer + fsync-per-COMMIT serializes concurrent writes — 40 results × ~1s/fsync under VPS I/O load = 42s avg finalize time. Redis SET is sub-ms regardless of concurrency. The persister batches SQLite writes (N rows, 1 fsync) for throughput. Billing uses its own Postgres pool so it can never starve the request path.

### 6. Reliability

**Visibility scanner** (`yapit/gateway/visibility_scanner.py`):
- Jobs move to processing set with timestamp when pulled
- Scanner runs every 15s, re-queues jobs stuck > 20s (constants in `gateway/__init__.py`)
- Retry count increments; jobs exceeding max retries → DLQ

**Dead letter queue:** `tts:dlq:{model}` (per-model). DLQ entries push error results so result_consumer cleans up.

### 7. Cache & Storage

- **Audio hot cache:** Redis (`tts:audio:{hash}`, 300s TTL). All recently synthesized audio lives here. Sub-ms reads.
- **Audio cold cache:** SQLite (`cache.py`) keyed by variant_hash. Dual persistent connections (reader for reads, writer for mutations) with WAL mode. LRU updates batched in-memory, flushed every ~10s. Populated by the cache persister.
- **Metadata:** BlockVariant in Postgres tracks duration_ms
- **Usage:** Characters recorded for billing on synthesis complete

### 8. Audio Fetch

Frontend fetches via HTTP:

- `yapit/gateway/api/v1/audio.py` — GET `/v1/audio/{variant_hash}`
- Checks Redis first (hot cache), falls back to SQLite (cold cache)
- Returns cached bytes directly (`audio/ogg` media type)

**CDN caching:** Response includes `Cache-Control: public, s-maxage=31536000, max-age=0` — Cloudflare edge caches audio indefinitely, browsers don't (the playback engine manages its own buffer). Content is hash-addressed and immutable, so edge caching is safe without purging. See [[infrastructure]] for the Cache Rule config and zone settings.

**Cache Rule details:** A CF Cache Rule matches `https://yapit.md/api/v1/audio/*` with `cache: true` (required since the URL has no file extension). Edge TTL mode is `bypass_by_default` (respects origin `s-maxage`). Browser TTL mode is `respect_origin` (passes through origin `max-age=0`). Without the explicit `browser_ttl: respect_origin`, CF's zone-level `browser_cache_ttl` (14400s) overrides `max-age=0`.

## Browser-Side Synthesis

Kokoro.js runs in a Web Worker (WASM/WebGPU) for free local TTS. Audio is resolved in-memory as `AudioBuffer` — no server submission. Browser TTS audio is NOT cached server-side; it only lives in the playback engine's in-memory variant cache for the session duration.

**Key files:**
- `frontend/src/lib/browserSynthesizer.ts` — Web Worker management, PCM→AudioBuffer conversion, generation-based cancellation
- `frontend/src/lib/serverSynthesizer.ts` — server (WebSocket) synthesis implementation
- `frontend/src/lib/synthesizer.ts` — shared `Synthesizer` interface
- `frontend/src/lib/browserTTS/worker.ts` — Web Worker running Kokoro.js

The `Synthesizer` interface unifies both paths — the playback engine doesn't care whether audio comes from browser or server. See [[frontend]] for the playback engine architecture.

## Models & Voices

Built-in models: kokoro, inworld-1.5, inworld-1.5-max. Model/voice definitions in `yapit/gateway/seed.py`. See [[inworld-tts]] for Inworld-specific details.

**OpenAI-compatible TTS** (`openai-tts` slug): configured via `OPENAI_TTS_BASE_URL` + `OPENAI_TTS_MODEL`. Voices are auto-discovered at startup via `GET /v1/audio/voices` (community extension — vLLM-Omni, Kokoro-FastAPI support it; OpenAI, AllTalk don't). Fallback: `OPENAI_TTS_VOICES` env var (comma-separated). Models without a configured backend are deactivated (`is_active=False`) so they don't appear in the API or voice picker. See `seed.py:sync_openai_tts_voices` and `seed.py:_deactivate_unconfigured_models`.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/ws.py` | WebSocket endpoint |
| `gateway/synthesis.py` | Synthesis orchestration (dedup, queuing, cache check) |
| `gateway/result_consumer.py` | Hot path: Redis SET audio, notify subscribers, push billing + persist events |
| `gateway/cache_persister.py` | Drain-on-wake batched Redis→SQLite persistence |
| `gateway/billing_consumer.py` | Cold path: BlockVariant update, usage billing, engagement stats |
| `gateway/visibility_scanner.py` | Re-queues stuck jobs |
| `workers/tts_loop.py` | Pull-based worker main loop |
| `workers/queue.py` | Shared queue utilities (push, pull, requeue) |
| `workers/adapters/*.py` | Model-specific synthesis |
| `contracts.py` | Shared types for gateway↔worker |
| `gateway/cache.py` | SQLite audio cache (async) |
| `gateway/domain_models.py` | Document, BlockVariant models |

## Gotchas

- **Billing is async, not in result_consumer:** `ws.py` checks usage limits (gating). Result consumer handles cache + notification only. Actual billing (`record_usage`) happens in `billing_consumer.py` via the `tts:billing:stream` Redis Stream. Billing is eventually consistent — a few seconds of delay is normal. At-least-once delivery with idempotent `record_usage` (dedup via `UsageLog.event_id`).
- **Per-block vs document-level errors:** Document-level errors use `error` message type (see table above). Per-block errors (usage limit exceeded) use `status` message type with `status="error"` field. Tests must check the correct message type.
- **Eviction timing:** Pending check happens at dequeue time, not enqueue. Jobs can sit in queue, then get skipped if cursor moved.
- **Variant sharing:** Two users requesting same text+model+voice share the cached audio. Good for efficiency, but means cache eviction affects everyone.
- **Empty audio / per-block failures:** Some blocks produce empty audio (whitespace-only text, garbage markup from extraction). Marked as "skipped" or "error" with `recoverable: true`. Frontend tracks these in a `resolvedEmpty` set so buffer readiness checks still work, and auto-advances past them. Only session-level errors (`recoverable: false`, e.g. usage limit) stop playback.
- **Usage multiplier:** Different models have different character costs. `TTSModel.usage_multiplier` in database. Passed in job to avoid DB query on finalization.
- **Voice change race condition:** WebSocket status messages include `model_slug` and `voice_slug` to prevent stale cache hits when user changes voice mid-playback. Without this, status messages from old voice arriving after reset would incorrectly mark blocks as cached.
- **Double synthesis prevention:** Inflight key deletion happens at START of result processing. First result atomically deletes key and proceeds; duplicates (from visibility timeout requeue + original completion) see delete() return 0 and skip. This prevents duplicate BillingEvents from being produced. On the consumer side, `record_usage` has its own idempotency via `UsageLog.event_id` (keyed on `job_id`) as a second line of defense.
- **Cache warming:** `yapit/gateway/warm_cache.py` is a one-shot CLI (not a background task). Run via `make warm-cache` when voices or showcase content change. Pinned entries are exempt from LRU eviction. See [[inworld-tts]] for details.
- **Inworld duration is estimated:** Calculated from OGG Opus file size (~14.5KB/sec assumption in adapter). Frontend uses decoded AudioBuffer for accurate playback timing.
- **OpenAI TTS audio format:** Requests `response_format="opus"`. If server returns OGG Opus (`OggS` magic bytes), passed through. Otherwise transcoded to OGG Opus via PyAV at 96kbps. Duration read from container metadata, falls back to byte-size estimate. Transcoding runs in executor to avoid blocking the event loop.
- **Codec is not part of variant hash:** In normal dev flow, `make dev-cpu` clears cache (`down -v`). If you run experiments without full teardown, stale cached blobs can make codec/endpoint A/B tests invalid.
- **Per-document pubsub channels:** Pubsub scoped to `tts:done:{user_id}:{document_id}` — prevents cross-tab contamination.
- **Eviction orphaning:** Inflight key stores `job_id`. On eviction, inflight key is conditionally deleted only if its value matches the evicted job — prevents orphaned semaphores from blocking future requests.
- **WS reconnect resilience:** `ServerSynthesizer` retries pending blocks on reconnect. `useTTSWebSocket` queues messages while disconnected, drains on connect.
- **Out-of-order block notifications:** Blocks are enqueued and processed in index order, but `result_consumer.py` spawns a concurrent task per result. Two tasks racing through their Redis calls can cause notifications to reach the frontend out of order. Cosmetic only (progress bar), playback is unaffected. Serializing the consumer would fix it but kill throughput for the parallel API dispatcher.
