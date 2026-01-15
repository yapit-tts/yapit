# TTS Flow

How text becomes audio in Yapit. The core synthesis pipeline from document blocks to playable audio.

## Overview

```
Document → Blocks → WebSocket request → Queue/Cache check → Synthesis → Cache → Notify → Fetch audio
```

How documents become blocks: see [[document-processing]].

**Key insight:** Audio is cached by content hash (`variant_hash`), not by document/block. Same text + model + voice = same audio, shared across users and documents.

## The Pipeline

### 1. Document → Blocks

Markdown processing creates speakable blocks with `audio_block_idx`:

- `yapit/gateway/processors/markdown/parser.py` — Parse markdown AST
- `yapit/gateway/processors/markdown/transformer.py` — Assign audio indices, split long blocks
- `yapit/gateway/processors/markdown/models.py` — StructuredDocument schema

Blocks with audio: heading, paragraph, list, blockquote. No audio: code, math, table, image, hr.

Block splitting: Markdown structure → paragraphs → sentence stoppers → hard cutoff. See `_split_into_sentences()` in transformer.

### 2. WebSocket Protocol

Frontend connects via WebSocket for real-time synthesis control:

- `yapit/gateway/api/v1/ws.py` — WebSocket endpoint
- `yapit/contracts.py` — Message types (WSSynthesisRequest, WSBlockStatus, etc.)

**Messages:**

| Direction | Type | Purpose |
|-----------|------|---------|
| Client→Server | `synthesize` | Request synthesis for block indices |
| Client→Server | `cursor_moved` | Evict blocks outside playback window |
| Server→Client | `block_status` | Status update (queued/processing/cached/error/skipped) |

**Cursor-aware eviction:** When cursor moves, backend evicts queued blocks the user likely won't play. Prevents wasting synthesis on skipped content.

### 3. Deduplication

Before queuing, check if variant already exists:

```
variant_hash = hash(text + model_slug + voice_slug + codec + voice_parameters)
```

- If cached → return audio URL immediately
- If in-flight → subscribe to existing job
- Otherwise → create job, queue it

See `BlockVariant.get_hash()` in `domain_models.py` and `_maybe_enqueue()` in `ws.py`.

### 4. Queue & Processing

Jobs go to model-specific Redis queues. Processors pull and synthesize:

- `yapit/gateway/processors/tts/manager.py` — TTSProcessorManager, routes config
- `yapit/gateway/processors/tts/base.py` — BaseTTSProcessor, queue loop
- `yapit/gateway/processors/tts/local.py` — LocalProcessor (HTTP to container)
- `yapit/gateway/processors/tts/runpod.py` — RunpodProcessor (serverless)
- `yapit/gateway/processors/tts/inworld.py` — InworldProcessor (streaming API)

**Route config:** `tts_processors.{dev,prod,ci}.json` — Maps model to processor class + backend.

**Overflow:** Kokoro can overflow to RunPod when local queue is deep. Configured per-route.

### 5. Workers

Actual model inference happens in workers:

- `yapit/workers/handlers/local.py` — FastAPI wrapper for adapters
- `yapit/workers/adapters/kokoro.py` — KokoroAdapter (local Kokoro-82M)
- RunPod workers run same adapters serverlessly

Workers return base64-encoded audio + duration. Gateway stores in cache.

### 6. Cache & Storage

- **Audio cache:** SQLite (`cache.py`) keyed by variant_hash
- **Metadata:** BlockVariant in Postgres tracks duration_ms, cache_ref
- **Usage:** Characters recorded for billing on synthesis complete

### 7. Audio Fetch

Frontend fetches via HTTP:

- `yapit/gateway/api/v1/audio.py` — GET `/v1/audio/{variant_hash}`
- PCM audio wrapped in WAV header on-the-fly
- Duration in `X-Duration-Ms` header

## Browser-Side Synthesis

Frontend can also synthesize locally via Kokoro WASM and submit audio via `POST /v1/audio`. See [[frontend]] for details.

## Models & Voices

See [[models-voices]] for model configuration, voice parameters, usage multipliers.

Current models: kokoro, higgs, inworld, inworld-max.

## Key Files

| File | Purpose |
|------|---------|
| `gateway/api/v1/ws.py` | WebSocket endpoint, synthesis orchestration |
| `gateway/processors/tts/manager.py` | Processor routing, background tasks |
| `gateway/processors/tts/base.py` | Queue consumer, finalization logic |
| `contracts.py` | Shared types for gateway↔worker |
| `gateway/cache.py` | SQLite audio cache |
| `gateway/domain_models.py` | Block, BlockVariant models |
| `workers/adapters/*.py` | Model-specific synthesis |

## Gotchas

- **Eviction timing:** Pending check happens at dequeue time, not enqueue. Jobs can sit in queue, then get skipped if cursor moved.
- **Variant sharing:** Two users requesting same text+model+voice share the cached audio. Good for efficiency, but means cache eviction affects everyone.
- **Empty audio:** Some blocks produce empty audio (whitespace-only). Marked as "skipped", frontend auto-advances.
- **Usage multiplier:** Different models have different character costs. `TTSModel.usage_multiplier` in database.
- **Voice change race condition:** WebSocket status messages include `model_slug` and `voice_slug` to prevent stale cache hits when user changes voice mid-playback. Without this, status messages from old voice arriving after reset would incorrectly mark blocks as cached. See `WSBlockStatus` in `contracts.py`.
