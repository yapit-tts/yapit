---
status: done
refs: []
---

# Playback engine doesn't recover from per-block failures

## Intent

Website extraction (trafilatura) sometimes produces garbage markup — e.g. decorative HTML elements extracted as empty image tags (`![]() | ![]() |`). markdown-it parses these as text nodes, producing TTS text like `! | ! | ! |`. This is valid transformer output — the text might produce audio on some models. But when it doesn't, the playback engine should recover gracefully. Currently it doesn't.

Two failure modes, both rooted in `playbackEngine.ts`:

### a) Kokoro: error on one block stops all playback

Kokoro produces no audio for punctuation → empty PCM → `av.AudioFrame.from_ndarray` on shape `(1, 0)` → `[Errno 12] Cannot allocate memory`. Error propagates correctly to frontend as `status="error"`.

**Bug:** `lastError` in `serverSynthesizer.ts` is sticky — set on ANY block error (line 255), only cleared on `cancelAll()` or cache hit (line 239). When `playBlock()` gets null + truthy `getError()` → `engineStop()`. One bad block kills the session.

### b) Inworld: stuck in "buffering" forever on skipped block

Inworld returns empty audio in 0.2s (confirmed via direct API test). Result consumer correctly sends `status="skipped"`. Synthesizer resolves null, no error.

**Bug:** In the `.then()` handler of `synthesizeBlock()` (line 295-319), skipped blocks (null result) don't enter `audioCache`, so `checkBufferReady()` is never called. The `else` branch only fires if `getError()` is truthy. Result: engine stuck in "buffering" waiting for cached blocks that will never arrive.

## Assumptions

- The MemoryError is specifically from `av.AudioFrame.from_ndarray` on empty int16 array. Confirmed by local repro and matching timestamps between `synthesis_queued` and `synthesis_error` events.
- Inworld does NOT hang — direct API test returns `audioContent: ""` in 0.2s. The stall is entirely client-side (playback engine buffering gap).
- `lastError` was designed for systemic errors (usage limit exceeded). Per-block failures getting the same treatment is a bug, not a feature.

## Done When

1. **Skipped blocks advance playback** — both during "buffering" (buffer readiness check accounts for skipped blocks) and "playing" (advance to next).
2. **Per-block errors skip to next block** — not `engineStop()`. Error banner shows briefly, auto-dismisses when a subsequent block plays successfully.
3. Systemic errors (usage limit) should still stop playback — need a way to distinguish per-block from systemic.

## Considered & Rejected

**Filter punctuation-only text in the transformer:** Wrong fix. Punctuation-only text might legitimately produce audio depending on the model. The backend is doing its job — the playback engine needs to be resilient to blocks that fail or get skipped, regardless of why.
