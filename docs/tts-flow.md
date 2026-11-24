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
| Client→Server | `watch` | Hear of the user's audio job over a document; sent on each connect and on opening a document |
| Server→Client | `status` | Per-block status update (queued/processing/cached/error/skipped). Includes `recoverable` bool — `false` only for session-level errors (usage limit). Playback engine advances past recoverable errors. |
| Server→Client | `evicted` | Blocks evicted after cursor move |
| Server→Client | `error` | Document-level errors (not found, invalid model) |
| Server→Client | `audio_job` | The document's audio job as it stands (`job` is null for none), after a `watch` and after each change |
| Server→Client | `audio_export` | An audio file the user asked for is a percent further (`status` `building`, with `progress` from 0 to 1), is built (`ready`) or could not be (`failed`, with `error`) |

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
- `tts:queue:{model}` — Sorted set with job_id as member, a timestamp as score; workers pop the lowest. Listener blocks are scored now, background audio job blocks now + 120 s (`BACKGROUND_DELAY_S` in `synthesis.py`). A retried job keeps the score it was pulled with.
- `tts:jobs` — Hash mapping job_id to job JSON
- `tts:job_index` — Hash mapping "user:doc:block" to job_id (for eviction)
- `tts:results` — List for completed results

**Runners** — two ways to schedule jobs, both calling `execute_job` from `yapit/synth.py`:
- `yapit/workers/tts_loop.py` → `run_tts_worker` — Sequential processing for GPU models (Kokoro). One job at a time, visibility tracking for retries. Runs on the worker image.
- `yapit/gateway/api_tts_dispatcher.py` → `run_api_tts_dispatcher` — Parallel processing for API models (OpenAI-compatible TTS). Spawns task per job, unlimited concurrency. No visibility tracking (if gateway crashes, in-flight jobs lost). Runs in the gateway process — the work is an outbound HTTP call, so it needs no worker of its own.

**Adapters:**
- `yapit/workers/kokoro/adapter.py` — Kokoro adapter (local model), worker image
- `yapit/gateway/openai_tts_adapter.py` — OpenAI-compatible adapter (any `/v1/audio/speech` endpoint). Requests `opus` format, detects OGG Opus via magic bytes (pass-through), transcodes other formats to OGG Opus via PyAV. Gateway image.

Workers only need Redis access. No Postgres, no HTTP endpoints. Gateway handles all DB writes and notifications centrally.

**Why pull-based:**
- Natural load balancing (faster workers pull more)
- Any device can be a worker (home GPU, VPS, cloud)
- Zero gateway changes to add/remove workers

### 5. Result Processing (Hot/Cold/Persist Split)

Three consumers with complete resource isolation:

**Result consumer (hot path)** — `yapit/gateway/result_consumer.py`

Pops from `tts:results`, spawns a task per result. No Postgres, no SQLite.
1. Claim the variant: the first result to arrive sets `tts:finalized:{hash}` (its job id, kept a day) and finalizes it; a later one is a duplicate and stops here
2. Redis SET audio (`tts:audio:{hash}`, 300s TTL), sub-ms. Then release the in-flight marker if this result's job holds it. A result with no audio sets `tts:skipped:{hash}` instead, and goes on to step 3 as `skipped`
3. Notify subscribers via Redis pubsub (user sees audio here)
4. XADD `BillingEvent` to `tts:billing:stream` (Redis Stream)
5. Push variant_hash to `tts:persist` for background SQLite persistence
6. Wake every background audio job awaiting the variant

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

### 7. Background audio jobs

A job synthesizes a chosen set of a document's blocks with no tab open, so playback later finds them in the cache. `POST /v1/documents/{id}/audio-job` takes a model, a voice and block ranges with titles; `GET` reports the job's status, its cached and total blocks and the blocks it still waits on, or null where the document has none; `DELETE` cancels it. `GET .../audio-job/estimate` gives, for a voice, the characters each block would bill (0 where cached) and what the user has left. A tab on the document hears of the job over the WebSocket: the feeder publishes its state on the document's channel after each top-up, the cancel endpoint after a cancel, and a `watch` publishes it once for the tab that sent it. The API is in `gateway/api/v1/audio_jobs.py`, the job in `gateway/audio_job.py`.

- **State** lives in Redis: `tts:audio_job:{user_id}` holds the user's latest job, its id, spec (with each block's text, so the document is parsed once, at the POST) and status. Its progress is keyed by its id: `tts:audio_job:{job_id}:awaited` holds the variants it waits on, `:next` how many of its blocks it has taken and `:lost` the ones to queue again. So a top-up still running for a job that was cancelled and replaced meanwhile writes only to its own job's keys, and a job ends only by its id. A user has one running job (`tts:audio_jobs_running`).
- **Slices:** at most 16 of a job's variants are in flight (`SLICE_SIZE`). The in-flight marker lives 600 s (`INFLIGHT_TTL_S` in `synthesis.py`), so a book queued at once would outlive it.
- **Feeder:** a gateway task blocks on `tts:audio_job_wake`; the result consumer pushes a user there for each result their job awaited (`tts:audio_job_waiters:{hash}`). The feeder then queues the job's next blocks through `request_synthesis(..., track_for_websocket=False, background=True)`: cache hits cost nothing, a variant already in flight is joined rather than queued twice, and the usage check runs per block. Once a minute it also reconciles every running job: it renews the in-flight marker of each job block still queued, so a slow queue never outlives it, and queues again any block lost with a gateway restart (no queued job, no marker, no audio).
- **Priority:** job blocks are scored 120 s late, so a listener's block is pulled before every job block queued in the two minutes before it. A listener asking for a variant whose job block waits moves that job to now (`ZADD XX LT` on the marker's job id). Cursor eviction skips a queued job an audio job awaits.
- **Bounds:** a job ends at `usage_limit` when the usage check refuses a block, and a plan with unlimited usage for the model runs a job to its last block; one running job per user is the only other bound. A deactivated voice or a document the user can no longer read ends it at `failed`.
- **End:** a job ends `done` when every block is prepared: its audio is cached, or the worker returned none for it (`tts:skipped:{hash}`). A block whose synthesis failed, or that the cache let go before the job's last block, ends the job at `failed`, naming how many blocks have no audio; generating again makes them.
- **Cancel** stops the job queueing and takes its queued blocks off the queue unless a listener or another job waits on them. Blocks a worker already took are finished, cached and billed.
- **Cache cap:** the POST refuses a selection whose estimated audio is larger than `AUDIO_CACHE_CONFIG__MAX_SIZE_MB`, since the cache would evict its first blocks before its last are made.

**Export** (`gateway/audio_export.py`): `POST /v1/documents/{id}/audio-export` takes a model, a voice, block ranges with titles and a format (`m4b`, AAC with a chapter per range; `mp3`, with ID3 chapters) and joins the ranges' cached blocks into one file, leaving out a block the worker returned no audio for. It is refused (409) while any other block has no audio in that voice, and while another file of the user's is being built. The file is built once into `AUDIO_EXPORT_DIR` under a name hashed from its content, and kept 24 hours: the answer is `ready` when the file is stored, or `building` with the build's `progress`, and the tabs on the document hear `audio_export` each percent the build gets further and when it ends. The panel shows that progress, then the download's. `GET .../audio-export/{key}.{format}` serves it, or answers 404 saying to save again once the file is gone. Each block is decoded and cut to the length it was encoded from (FFmpeg leaves the encoder's padding on a block of one Ogg page), so the joins carry no gap. A build is one encoder, the event loop handing it block after block; the blocks are decoded ahead of it on the same few low-priority threads (`_build_threads`). `experiments/audio_export_benchmark.py` times a build and checks its file, and its measurements are in `experiments/audio_export_benchmark_results.jsonl`.

- **Bound:** the files and the builds writing them take at most `AUDIO_EXPORT_MAX_SIZE_MB` (`ExportStore`). Before a build writes, it holds room for what it will write: twice the bit rate per second of audio, then both copies of the stream while the chapters are added. The oldest files no download is serving are deleted to make that room. A build that gets none fails, saying to save again later, or that the file is too large for the bound.
- **Downloads:** a download keeps its file until it ends, or until a deadline set by its size (`DOWNLOAD_GRACE_S`, `DOWNLOAD_MIN_BYTES_PER_S` in `api/v1/audio_jobs.py`), so a client that stops reading cannot keep files from being deleted.
- **Two gateways:** each counts its own builds. During a deploy (start-first) both run on the volume, so the directory can briefly hold up to twice the bound. The hourly sweep counts the directory as it stands, files and scratch the other gateway wrote included, and deletes scratch nothing has written for an hour.

### 8. Cache & Storage

- **Audio hot cache:** Redis (`tts:audio:{hash}`, 300s TTL). All recently synthesized audio lives here. Sub-ms reads.
- **Audio cold cache:** SQLite (`cache.py`) keyed by variant_hash. Dual persistent connections (reader for reads, writer for mutations) with WAL mode. LRU updates batched in-memory, flushed every ~10s. Populated by the cache persister.
- **Metadata:** BlockVariant in Postgres tracks duration_ms
- **Usage:** Characters recorded for billing on synthesis complete

### 9. Audio Fetch

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

Built-in model: kokoro. Model/voice definitions in `yapit/gateway/seed.py`.

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
| `gateway/audio_job.py` | Background audio jobs: state, feeder, cancel |
| `gateway/api/v1/audio_jobs.py` | Audio job and export endpoints |
| `gateway/audio_export.py` | Export: the join into one file, its storage and expiry |
| `workers/tts_loop.py` | Pull-based worker main loop (worker image) |
| `gateway/api_tts_dispatcher.py` | Parallel dispatcher for API models (gateway image) |
| `queue.py` | Shared queue utilities (push, pull, requeue) |
| `synth.py` | Shared `SynthAdapter` interface + `execute_job` |
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
- **Double synthesis prevention:** The first result for a variant finalizes it by setting `tts:finalized:{hash}` to its job id, kept a day, longer than any job for the variant can still be queued or in flight; duplicates (from visibility timeout requeue + original completion, or a second job queued after the first's marker expired) find it set and skip. A job queued once the variant is gone from the cache reopens it (`open:<job_id>`), so that job alone may finalize it again. This prevents duplicate BillingEvents from being produced. A result whose marker expired is still kept. On the consumer side, `record_usage` has its own idempotency via `UsageLog.event_id` (keyed on `job_id`) as a second line of defense.
- **Cache warming:** `yapit/gateway/warm_cache.py` is a one-shot CLI (not a background task). Run via `make warm-cache` when voices or showcase content change. Pinned entries are exempt from LRU eviction.
- **OpenAI TTS audio format:** Requests `response_format="opus"`. If server returns OGG Opus (`OggS` magic bytes), passed through. Otherwise transcoded to OGG Opus via PyAV at 96kbps. Duration read from container metadata, falls back to byte-size estimate. Transcoding runs in executor to avoid blocking the event loop.
- **Codec is not part of variant hash:** In normal dev flow, `make dev-cpu` clears cache (`down -v`). If you run experiments without full teardown, stale cached blobs can make codec/endpoint A/B tests invalid.
- **Per-document pubsub channels:** Pubsub scoped to `tts:done:{user_id}:{document_id}` — prevents cross-tab contamination.
- **Eviction orphaning:** Inflight key stores `job_id`. On eviction and on a result, the inflight key is deleted only if its value matches that job. This prevents orphaned semaphores from blocking future requests, and one job's result from releasing another's marker.
- **WS reconnect resilience:** `ServerSynthesizer` retries pending blocks on reconnect. `useTTSWebSocket` queues messages while disconnected, drains on connect.
- **Out-of-order block notifications:** Blocks are enqueued and processed in index order, but `result_consumer.py` spawns a concurrent task per result. Two tasks racing through their Redis calls can cause notifications to reach the frontend out of order. Cosmetic only (progress bar), playback is unaffected. Serializing the consumer would fix it but kill throughput for the parallel API dispatcher.
