# Inworld TTS

Premium TTS provider. REST streaming API, 65 voices across 15 languages.

## Gotchas

**Model ID format uses dots, not dashes:** The API model IDs are `inworld-tts-1.5-mini` and `inworld-tts-1.5-max` (with dots in "1.5"). Using dashes like `inworld-tts-1-5-mini` returns 400 Bad Request.

**Voice listing requires separate API scope:** The synthesis API key doesn't have permissions to call `/voices/v1/voices`. Need a key with voice management scope, or check the [TTS Playground](https://platform.inworld.ai/tts-playground) manually.

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

## Key Files

- `yapit/workers/adapters/inworld.py` — REST streaming adapter
- `yapit/data/inworld/voices.json` — 65 voices (en, zh, nl, fr, de, it, ja, ko, pl, pt, es, ru, hi, ar, he)
- `yapit/gateway/seed.py:96-139` — model/voice definitions
- `frontend/src/lib/voiceSelection.ts` — `INWORLD_SLUG`, `INWORLD_MAX_SLUG` constants + `isInworldModel()` helper

**For model version upgrades:** Update the two slug constants in `voiceSelection.ts` — all comparison sites use the helper or constants, so only one file changes.

## Related Tasks

- [[inworld-api-evaluation]] — original evaluation, API research, voice selection
- [[inworld-frontend-integration]] — voice picker, MP3 decoding fix
- [[2026-01-21-inworld-tts-1.5-upgrade]] — upgrade to TTS-1.5 models
- [[2026-01-18-inworld-temperature-setting]] — temperature slider (pending)

## External Docs

- [API: Generating Audio](https://docs.inworld.ai/docs/tts/capabilities/generating-audio) — request format, parameters
- [TTS-1 Technical Report](https://arxiv.org/html/2507.21138v1) — architecture, streaming, codec
