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
| Server→Client | `status` | Per-block status update (queued/processing/cached/error/skipped) |
| Server→Client | `evicted` | Blocks evicted after cursor move |
| Server→Client | `error` | Document-level errors (not found, invalid model) |

**Cursor-aware eviction:** When cursor moves, backend evicts queued blocks the user likely won't play. Uses sorted set for O(log N) eviction.

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
  - `run_api_tts_dispatcher` — Parallel processing for API models (Inworld). Spawns task per job, unlimited concurrency. No visibility tracking (if gateway crashes, in-flight jobs lost).
- `yapit/workers/adapters/kokoro.py` — Kokoro adapter (local model)
- `yapit/workers/adapters/inworld.py` — Inworld adapter (API calls, with retry logic for 429/500/503/504)

Workers only need Redis access. No Postgres, no HTTP endpoints. Gateway handles all DB writes and notifications centrally.

**Why pull-based:**
- Natural load balancing (faster workers pull more)
- Any device can be a worker (home GPU, VPS, RunPod)
- Zero gateway changes to add/remove workers

### 5. Result Processing (Hot/Cold Split)

Two consumers with complete resource isolation:

**Result consumer (hot path)** — `yapit/gateway/result_consumer.py`

Pops from `tts:results`, spawns a task per result. No Postgres.
1. Atomically claim result (inflight key dedup)
2. Write audio to SQLite cache
3. Notify subscribers via Redis pubsub (user sees audio here)
4. Push `BillingEvent` to `tts:billing` Redis list

**Billing consumer (cold path)** — `yapit/gateway/billing_consumer.py`

Pops from `tts:billing` serially. Own Postgres connection pool (2 connections), isolated from request path.
1. Update BlockVariant metadata (duration_ms, cache_ref)
2. Record usage via `record_usage()` (waterfall billing)
3. Upsert engagement stats (UserVoiceStats)

**Why the split:** Fast GPU workers can dump 40+ results in seconds. Previously, each result held a Postgres connection for billing (FOR UPDATE lock on subscription row). 30+ connections held by billing tasks waiting for the lock → pool exhaustion → WebSocket request path starved → new blocks can't be queued → workers idle. The hot path is now Postgres-free, and the cold path uses its own pool so it can never interfere with the request path.

### 6. Reliability

**Visibility scanner** (`yapit/gateway/visibility_scanner.py`):
- Jobs move to processing set with timestamp when pulled
- Scanner runs every 15s, re-queues jobs stuck > 20s (constants in `gateway/__init__.py`)
- Retry count increments; jobs exceeding max retries → DLQ

**Overflow scanner** (`yapit/gateway/overflow_scanner.py`):
- Native async (`AsyncioEndpoint`), claims all stale jobs per cycle
- Polls outstanding RunPod handles across cycles
- Failures requeue with retry; at max retries → DLQ + error result to `tts:results`

**Dead letter queue:** `tts:dlq:{model}` (per-model). DLQ entries push error results so result_consumer cleans up.

### 7. Cache & Storage

- **Audio cache:** SQLite (`cache.py`) keyed by variant_hash. Dual persistent connections (reader for reads, writer for mutations) with WAL mode. LRU updates batched in-memory, flushed every ~10s to avoid write contention on reads
- **Metadata:** BlockVariant in Postgres tracks duration_ms, cache_ref
- **Usage:** Characters recorded for billing on synthesis complete

### 8. Audio Fetch

Frontend fetches via HTTP:

- `yapit/gateway/api/v1/audio.py` — GET `/v1/audio/{variant_hash}`
- Returns cached bytes directly (`audio/ogg` media type)

## Browser-Side Synthesis

Kokoro.js runs in a Web Worker (WASM/WebGPU) for free local TTS. Audio is resolved in-memory as `AudioBuffer` — no server submission. Browser TTS audio is NOT cached server-side; it only lives in the playback engine's in-memory variant cache for the session duration.

**Key files:**
- `frontend/src/lib/browserSynthesizer.ts` — Web Worker management, PCM→AudioBuffer conversion, generation-based cancellation
- `frontend/src/lib/serverSynthesizer.ts` — server (WebSocket) synthesis implementation
- `frontend/src/lib/synthesizer.ts` — shared `Synthesizer` interface
- `frontend/src/lib/browserTTS/worker.ts` — Web Worker running Kokoro.js

The `Synthesizer` interface unifies both paths — the playback engine doesn't care whether audio comes from browser or server. See [[frontend]] for the playback engine architecture.

## Models & Voices

Current models: kokoro, inworld-1.5, inworld-1.5-max. Model/voice definitions in `yapit/gateway/seed.py`. See [[inworld-tts]] for Inworld-specific details.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/ws.py` | WebSocket endpoint |
| `gateway/synthesis.py` | Synthesis orchestration (dedup, queuing, cache check) |
| `gateway/result_consumer.py` | Hot path: cache audio, notify subscribers, push billing event |
| `gateway/billing_consumer.py` | Cold path: BlockVariant update, usage billing, engagement stats |
| `gateway/visibility_scanner.py` | Re-queues stuck jobs |
| `gateway/overflow_scanner.py` | Sends stale jobs to RunPod |
| `workers/tts_loop.py` | Pull-based worker main loop |
| `workers/queue.py` | Shared queue utilities (push, pull, requeue) |
| `workers/adapters/*.py` | Model-specific synthesis |
| `contracts.py` | Shared types for gateway↔worker |
| `gateway/cache.py` | SQLite audio cache (async) |
| `gateway/domain_models.py` | Block, BlockVariant models |

## Gotchas

- **Billing is async, not in result_consumer:** `ws.py` checks usage limits (gating). Result consumer handles cache + notification only. Actual billing (`record_usage`) happens in `billing_consumer.py` via the `tts:billing` Redis queue. Billing is eventually consistent — a few seconds of delay is normal.
- **Per-block vs document-level errors:** Document-level errors use `error` message type (see table above). Per-block errors (usage limit exceeded) use `status` message type with `status="error"` field. Tests must check the correct message type.
- **Eviction timing:** Pending check happens at dequeue time, not enqueue. Jobs can sit in queue, then get skipped if cursor moved.
- **Variant sharing:** Two users requesting same text+model+voice share the cached audio. Good for efficiency, but means cache eviction affects everyone.
- **Empty audio:** Some blocks produce empty audio (whitespace-only). Marked as "skipped", frontend auto-advances.
- **Usage multiplier:** Different models have different character costs. `TTSModel.usage_multiplier` in database. Passed in job to avoid DB query on finalization.
- **Voice change race condition:** WebSocket status messages include `model_slug` and `voice_slug` to prevent stale cache hits when user changes voice mid-playback. Without this, status messages from old voice arriving after reset would incorrectly mark blocks as cached.
- **Double billing prevention:** Inflight key deletion happens at START of result processing. First result atomically deletes key and proceeds; duplicates (from visibility timeout requeue + original completion) see delete() return 0 and skip.
- **Cache warming:** `yapit/gateway/warm_cache.py` pre-synthesizes voice previews and showcase documents. Runs as a gateway background task on startup.
- **Inworld duration is estimated:** Calculated from OGG Opus file size (~14.5KB/sec assumption in adapter). Frontend uses decoded AudioBuffer for accurate playback timing.
- **Codec is not part of variant hash:** In normal dev flow, `make dev-cpu` clears cache (`down -v`). If you run experiments without full teardown, stale cached blobs can make codec/endpoint A/B tests invalid.
- **Per-document pubsub channels:** Pubsub scoped to `tts:done:{user_id}:{document_id}` — prevents cross-tab contamination.
- **Eviction orphaning:** Inflight key stores `job_id`. On eviction, inflight key is conditionally deleted only if its value matches the evicted job — prevents orphaned semaphores from blocking future requests.
- **WS reconnect resilience:** `ServerSynthesizer` retries pending blocks on reconnect. `useTTSWebSocket` queues messages while disconnected, drains on connect.
