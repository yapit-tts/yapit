---
status: done
started: 2026-01-12
completed: 2026-02-09
---

# Task: Audio Cache Opus Compression

## Intent

Reduce audio cache storage by ~5x by compressing TTS output with Opus codec before caching. Currently storing uncompressed audio (WAV/PCM), which is wasteful.

**Why Opus:**
- Designed specifically for speech — excellent quality at low bitrates
- 32-64 kbps for good speech quality = ~15-30 MB/hour (vs ~158 MB/hour uncompressed)
- All modern browsers support Opus natively (2026) — can serve directly without transcoding
- Open, royalty-free codec

## Sources

**Current implementation:**
- `yapit/gateway/processors/tts/base.py` — `finalize_synthesis()` stores audio via `self._cache.store()`
- `yapit/gateway/cache.py` — SQLite cache, stores raw bytes

**Opus resources:**
- [Opus Codec](https://opus-codec.org/) — official site
- Python: `opuslib` or `pyogg` for encoding

**Inworld API natively supports Opus output:**
- [Inworld Generating Audio docs](https://docs.inworld.ai/docs/tts/capabilities/generating-audio) — lists Opus as supported format (8-48kHz, 32-192kbps)
- Just change `"audio_encoding": "MP3"` → `"OPUS"` in `yapit/workers/adapters/inworld.py`
- No transcoding needed for Inworld — only Kokoro/Higgs need PCM→Opus conversion

## Key Decisions

### Encode on store, serve directly

- Encode to Opus when storing in cache
- Serve Opus directly to browser (no decode on retrieval)
- Browser decodes natively
- Quality loss: negligible for speech

### Bitrate

- 48 kbps is good default for speech (clear, small)
- Could make configurable if needed

### File format

- `.opus` in OGG container (standard, well-supported)
- Or raw Opus in WebM container (also well-supported)

## Done When

- [ ] Add Opus encoding to TTS cache storage
- [ ] Update audio serving endpoint to set correct Content-Type
- [ ] Verify playback works in Chrome, Firefox, Safari
- [ ] Measure actual storage reduction

## Constraints

- Don't break existing cached audio (migration path or just let old cache expire)
- Encoding should be fast enough to not add noticeable latency

## Commits

- `1d69419` — feat: switch all TTS audio to OGG Opus, drop TTSModel codec columns

## Related

- [[2026-02-09-inworld-opus-firefox-artifact]] — Firefox startup artifact found during this work, fixed by using streaming endpoint
- [[2026-01-12-gemini-processor-integration]] — mentions audio cache LRU as separate task
- Audio cache also needs LRU implementation (same pattern as extraction cache)
