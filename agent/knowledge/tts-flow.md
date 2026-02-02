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

Block splitting: Markdown structure → paragraphs → sentence stoppers → hard cutoff. See `_split_into_sentences()` in transformer.

### 2. WebSocket Protocol

Frontend connects via WebSocket for real-time synthesis control:

- `yapit/gateway/api/v1/ws.py` — WebSocket endpoint, synthesis orchestration
- `yapit/contracts.py` — Job/result types (SynthesisJob, WorkerResult)

**Messages:**

| Direction | Type | Purpose |
|-----------|------|---------|
| Client→Server | `synthesize` | Request synthesis for block indices |
| Client→Server | `cursor_moved` | Evict blocks outside playback window |
| Server→Client | `block_status` | Status update (queued/processing/cached/error/skipped) |

**Cursor-aware eviction:** When cursor moves, backend evicts queued blocks the user likely won't play. Uses sorted set for O(log N) eviction.

### 3. Deduplication

Before queuing, check if variant already exists:

```
variant_hash = hash(text + model_slug + voice_slug + codec + voice_parameters)
```

- If cached → return audio URL immediately
- If in-flight → subscribe to existing job
- Otherwise → create job, queue it

See `BlockVariant.get_hash()` in `domain_models.py` and `_maybe_enqueue()` in `ws.py`.

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

### 5. Result Consumer

`yapit/gateway/result_consumer.py`

Background task that consumes from `tts:results` and finalizes:
1. Write audio to SQLite cache
2. Create/update BlockVariant in Postgres
3. Record usage for billing
4. Notify subscribers via Redis pubsub

### 6. Reliability

**Visibility scanner** (`yapit/gateway/visibility_scanner.py`):
- Jobs move to processing set with timestamp when pulled
- Scanner runs every 15s, re-queues jobs stuck > 30s
- Retry count increments; jobs exceeding max retries → DLQ

**Overflow scanner** (`yapit/gateway/overflow_scanner.py`):
- Monitors queue depth; jobs waiting > 30s trigger overflow
- Sends stale jobs to RunPod serverless as fallback
- Per-model configurable thresholds

**Dead letter queue:** Jobs that fail repeatedly go to `tts:dlq`. Alert on DLQ growth.

### 7. Cache & Storage

- **Audio cache:** SQLite (`cache.py`) keyed by variant_hash. Dual persistent connections (reader for reads, writer for mutations) with WAL mode. LRU updates batched in-memory, flushed every ~10s to avoid write contention on reads
- **Metadata:** BlockVariant in Postgres tracks duration_ms, cache_ref
- **Usage:** Characters recorded for billing on synthesis complete

### 8. Audio Fetch

Frontend fetches via HTTP:

- `yapit/gateway/api/v1/audio.py` — GET `/v1/audio/{variant_hash}`
- PCM audio wrapped in WAV header on-the-fly

## Browser-Side Synthesis

Kokoro.js runs in a Web Worker (WASM/WebGPU) for free local TTS. Audio is resolved in-memory as `AudioBuffer` — no server submission. Browser TTS audio is NOT cached server-side; it only lives in the playback engine's in-memory variant cache for the session duration.

**Key files:**
- `frontend/src/lib/browserSynthesizer.ts` — Web Worker management, PCM→AudioBuffer conversion, generation-based cancellation
- `frontend/src/lib/serverSynthesizer.ts` — server (WebSocket) synthesis implementation
- `frontend/src/lib/synthesizer.ts` — shared `Synthesizer` interface
- `frontend/src/lib/browserTTS/worker.ts` — Web Worker running Kokoro.js

The `Synthesizer` interface unifies both paths — the playback engine doesn't care whether audio comes from browser or server. See [[frontend]] for the playback engine architecture.

## Models & Voices

See [[models-voices]] for model configuration, voice parameters, usage multipliers.

Current models: kokoro, inworld-1.5, inworld-1.5-max. HIGGS removed (API models simpler to support as premium, avoiding RunPod complexity and higher costs).

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/ws.py` | WebSocket endpoint, synthesis orchestration |
| `gateway/result_consumer.py` | Consumes results, finalizes (cache, DB, billing) |
| `gateway/visibility_scanner.py` | Re-queues stuck jobs |
| `gateway/overflow_scanner.py` | Sends stale jobs to RunPod |
| `workers/tts_loop.py` | Pull-based worker main loop |
| `workers/queue.py` | Shared queue utilities (push, pull, requeue) |
| `workers/adapters/*.py` | Model-specific synthesis |
| `contracts.py` | Shared types for gateway↔worker |
| `gateway/cache.py` | SQLite audio cache (async) |
| `gateway/domain_models.py` | Block, BlockVariant models |

## Gotchas

- **Billing happens in result_consumer, not ws.py:** `ws.py` only checks usage limits (gating). Actual billing (`record_usage`) happens in `result_consumer.py` after synthesis completes. Don't look for billing code in ws.py.
- **Per-block vs document-level errors:** Document-level errors (not found, invalid model) send `{"type": "error", ...}`. Per-block errors (usage limit exceeded) send `WSBlockStatus` with `type="status"` and `status="error"`. Tests must check the correct field.
- **Eviction timing:** Pending check happens at dequeue time, not enqueue. Jobs can sit in queue, then get skipped if cursor moved.
- **Variant sharing:** Two users requesting same text+model+voice share the cached audio. Good for efficiency, but means cache eviction affects everyone.
- **Empty audio:** Some blocks produce empty audio (whitespace-only). Marked as "skipped", frontend auto-advances.
- **Usage multiplier:** Different models have different character costs. `TTSModel.usage_multiplier` in database. Passed in job to avoid DB query on finalization.
- **Voice change race condition:** WebSocket status messages include `model_slug` and `voice_slug` to prevent stale cache hits when user changes voice mid-playback. Without this, status messages from old voice arriving after reset would incorrectly mark blocks as cached.
- **Double billing prevention:** Inflight key deletion happens at START of result processing. First result atomically deletes key and proceeds; duplicates (from visibility timeout requeue + original completion) see delete() return 0 and skip.
- **Cache warming:** `yapit/gateway/warm_cache.py` pre-synthesizes voice preview sentences for all active models/voices. Run via systemd timer (`scripts/warm_cache.timer`) daily at 04:00. Uses `synthesize_and_wait()` to go through the normal queue→worker→cache pipeline.
- **Inworld duration is estimated:** Calculated from MP3 file size (~16KB/sec). Frontend uses decoded AudioBuffer for accurate playback timing.
- **Cross-tab voice contamination:** Multiple tabs playing the same document with different voices share the same Redis pubsub channel. A notification from one voice would incorrectly update the other tab. Fix: Compare incoming `model_slug` and `voice_slug` against what was requested; ignore mismatched notifications.
