# Inworld TTS

Premium TTS provider. REST streaming API, 113 voices across 15 languages (73 English).

## Gotchas

**Model ID format uses dots, not dashes:** The API model IDs are `inworld-tts-1.5-mini` and `inworld-tts-1.5-max` (with dots in "1.5"). Using dashes like `inworld-tts-1-5-mini` returns 400 Bad Request.

**Voice listing endpoint is deprecated (July 2026):** `GET /tts/v1/voices` still works with the synthesis API key as of 2026-02. The voices themselves and the synthesis API are NOT deprecated — only the listing endpoint. Voice data is canonical in `yapit/data/inworld/voices.json`; no need to call the API at runtime.

**Streaming vs non-streaming are not acoustically equivalent at block start:** In local testing, non-streaming (`/tts/v1/voice`) produced noticeably higher first 10-20ms energy than streaming (`/tts/v1/voice:stream`) for the same text/voice/model/codec. This was audible as a startup artifact in Firefox. Streaming removed the artifact.

**Use the right payload shape per endpoint:**
- `/tts/v1/voice:stream` expects snake_case (`voice_id`, `model_id`, `audio_config`, `audio_encoding`, `sample_rate_hertz`)
- `/tts/v1/voice` expects camelCase (`voiceId`, `modelId`, `audioConfig`, `audioEncoding`, `sampleRateHertz`)

**`LINEAR16` response is WAV-wrapped:** Inworld returns RIFF/WAV bytes for `LINEAR16`, not bare PCM. Parse WAV properly before treating payload as samples.

**OGG_OPUS (non-streaming) returns stereo:** Observed 2-channel output despite docs often implying mono.

**Codec experiments can be invalidated by cache reuse:** `variant_hash` currently does not include codec. In normal dev flow, `make dev-cpu` clears caches (`down -v`) so this is handled. If you test without full teardown, stale cached blobs can invalidate A/B results.

## Canonical Path (2026-02)

Current inworld adapter path (`yapit/workers/adapters/inworld.py`):

- Endpoint: `/tts/v1/voice:stream`
- Codec: `OGG_OPUS`
- Sample rate: `48_000`

This is the canonical path because it eliminated the Firefox startup artifact seen with non-streaming responses.

## Models

| Model | API ID | Our Slug | Price | Latency (P50) |
|-------|--------|----------|-------|---------------|
| TTS-1.5-Mini | `inworld-tts-1.5-mini` | `inworld-1.5` | $5/1M chars | ~120ms |
| TTS-1.5-Max | `inworld-tts-1.5-max` | `inworld-1.5-max` | $10/1M chars | ~200ms |

## Speaking Rate

**~14 chars/sec average** (n=8 voices, ~3500 chars corpus)

| Voice | chars/sec | Notes |
|-------|-----------|-------|
| Sarah | 15.71 | Fast-talking |
| Craig | 15.60 | |
| Dennis | 15.16 | |
| Ashley | 14.30 | |
| Olivia | 14.23 | |
| Mark | 13.74 | |
| Elizabeth | 13.58 | |
| Blake | 11.21 | Intimate/deliberate |

**Variance:** 11.2 - 15.7 chars/sec (~40% spread). Blake is a clear outlier (intimate reading style). Excluding Blake, range is 13.6-15.7 (~15% spread).

**For quota estimation:**
- Conservative: 12 chars/sec → 43,200 chars/hour
- Average: 14 chars/sec → 50,400 chars/hour
- Fast voice: 16 chars/sec → 57,600 chars/hour

Benchmark: `experiments/benchmark_inworld_speaking_rate.py`

## Voices

113 voices across 15 languages. Canonical source: `yapit/data/inworld/voices.json` (fetched from `GET /tts/v1/voices`). Same voices are shared between both inworld-1.5 and inworld-1.5-max models.

**Adding voices:** Update `voices.json` from the API, then:
- Dev/self-host: seed script auto-syncs missing voices on startup (`_sync_inworld_voices` in `seed.py`)
- Prod: direct SQL INSERT (see pattern in git history: `231922c`), then `make warm-cache`

**Voice picker** has search (name + description substring match) in the Inworld tab. With 73 EN voices, search is essential.

## Cache Warming & Pinning

Showcase docs and voice previews are pre-synthesized and **pinned** in the SQLite audio cache — pinned entries are exempt from LRU eviction. See [[tts-flow]] for cache architecture.

- `yapit/gateway/warm_cache.py` — one-shot CLI, run via `make warm-cache` on prod
- Warming synthesizes missing entries, then bulk-pins all warmed variant hashes
- No background warming loop — run manually when voices or showcase content change

## Key Files

- `yapit/workers/adapters/inworld.py` — REST streaming adapter
- `yapit/data/inworld/voices.json` — 113 voices, canonical voice data
- `yapit/gateway/seed.py` — model/voice definitions, additive voice sync
- `yapit/gateway/warm_cache.py` — one-shot cache warming + pinning
- `frontend/src/components/voicePicker.tsx` — voice picker with search
- `frontend/src/lib/voiceSelection.ts` — `INWORLD_SLUG`, `INWORLD_MAX_SLUG` constants

**For model version upgrades:** Update the two slug constants in `voiceSelection.ts` — all comparison sites use the helper or constants, so only one file changes.

## External Docs

- [API: Generating Audio](https://docs.inworld.ai/docs/tts/capabilities/generating-audio) — request format, parameters
- [TTS-1 Technical Report](https://arxiv.org/html/2507.21138v1) — architecture, streaming, codec
