---
status: done
started: 2026-02-01
---

# Task: Browser TTS Synthesizer Abstraction & Bug Fixes

## Intent

Refactor browser-side TTS to use a clean synthesizer abstraction shared with the server path. Currently the playback engine has `isServerSideModel()` branches sprinkled throughout, a React render-cycle middleman for browser synthesis, a voice-change bug that caches audio under the wrong key, and no error surfacing when local TTS fails. The goal is a unified architecture where the engine doesn't know or care where audio comes from.

Triggered by a user report: RTX 3080, Linux Mint, Brave — local models silently fail, no banner shown, no errors visible. Root cause: shallow WebGPU detection (`!!navigator.gpu` vs `requestAdapter()`), plus no error surfacing in the UI.

## Assumptions

- MIN_BUFFER_TO_START = 2 stays, applied uniformly to both server and browser modes
- Worker cannot cancel mid-generation, only between blocks — acceptable
- Worker should never be terminated/recreated on voice change (model reload is ~2-5s)
- Kokoro model downloaded on-the-fly from HuggingFace (via kokoro-js/Transformers.js) is the right approach — no bundling
- `POST /v1/audio` endpoint is dead code and can be deleted
- Tips page content (WebGPU troubleshooting, Brave flags, etc.) is a separate follow-up task
- Mobile: local TTS is already blocked on mobile, stays that way

## Architecture

### Current problems

1. **Engine has two code paths** — `isServerSideModel()` checks in: `synthesizeBlock`, `triggerPrefetch`, `checkAndRefillBuffer`, `deriveBlockStates`, `play`, `stop`, `seekToBlock`, `setVoice`
2. **React middleman** — engine creates resolvers, React effect (runs every render) reads `getPendingBrowserBlocks()`, dispatches to worker, feeds results back. Awkward coupling.
3. **Voice-change stale audio bug** — `onBrowserAudio` uses engine's current model/voiceSlug (new voice) to cache audio that was synthesized for the old voice. Server path correctly uses the message's model/voice.
4. **No cancellation** — worker processes all queued blocks even after voice change
5. **No error surfacing** — `browserTTS.error` state is set but never displayed
6. **Shallow WebGPU detection** — banner uses `!!navigator.gpu`, worker uses `requestAdapter()`. They disagree on capability.

### Target design

```
Engine (unchanged core: caching, buffering, playback, eviction)
  │
  │  Synthesizer interface:
  │    synthesize(blockIdx, text, model, voice) → Promise<AudioBufferData | null>
  │    cancel() → void
  │    getError() → string | null
  │
  ├─ ServerSynthesizer: WS connection, batching, cursor_moved
  └─ BrowserSynthesizer: worker lifecycle, cancel support, device detection
```

Engine gets a `synthesize` function (+ cancel, error) injected. All `isServerSideModel` branches collapse. Buffering logic becomes uniform. `getPendingBrowserBlocks()`, `onBrowserAudio()`, `cancelBrowserBlock()` removed.

Voice-change bug fixed by construction: synthesizer owns its requests and tags them. Engine calls `cancel()` on voice change, synthesizer drops stale work.

### Synthesizer interface details

- `synthesize()` is called by the engine per-block. Returns a promise that resolves with audio data or null (cancelled/error).
- `cancel()` cancels all pending synthesis. BrowserSynthesizer sends cancel to worker + rejects pending promises. ServerSynthesizer stops caring about old-voice WS messages.
- `getError()` returns current error string or null. Engine exposes this in snapshot for UI.
- On voice change: engine calls `cancel()`, creates new synthesis requests with new voice. Synthesizer handles the rest.

### Worker cancellation

Add `cancel` message type to worker. On receipt, worker clears any internally queued work. Current in-flight `tts.generate()` call completes (can't abort), but result is discarded by the BrowserSynthesizer (voice mismatch check). No worker termination.

### WebGPU detection

Both banner hook and worker use the same logic:
```typescript
async function detectWebGPU(): Promise<boolean> {
  if (!navigator.gpu) return false;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return adapter !== null && !adapter.isFallbackAdapter;
  } catch {
    return false;
  }
}
```
Fallback adapter treated same as no adapter — use WASM q8 instead of WebGPU fp32.

### Error surfacing

- Engine snapshot gets a `synthesizerError: string | null` field
- UI shows error banner near playback controls (same pattern as quota-reached banner in soundControl.tsx)
- Banner text: "Local processing failed — switch to cloud or learn more"
- Auto-clears when user switches model (error comes from synthesizer, new synthesizer has no error)
- Informational case: worker reports `device: "wasm"` → "Using CPU processing (WebGPU unavailable)" — not an error, just a heads-up

### Dead code removal

- Delete `POST /v1/audio` endpoint (`yapit/gateway/api/v1/audio.py`)
- Delete `AudioSubmitRequest` / `AudioSubmitResponse` schemas
- Delete any route registration for the audio submit endpoint

## Sources

**Knowledge files:**
- [[tts-flow]] — audio synthesis pipeline context
- [[frontend]] — React architecture, component hierarchy

**Key code files:**
- MUST READ: `frontend/src/lib/playbackEngine.ts` — the engine being refactored (~880 lines)
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — React hook that drives browser synthesis (the middleman being eliminated)
- MUST READ: `frontend/src/lib/browserTTS/worker.ts` — web worker for Kokoro inference
- MUST READ: `frontend/src/lib/browserTTS/useBrowserTTS.ts` — React hook wrapping the worker
- MUST READ: `frontend/src/hooks/useWebGPU.ts` — WebGPU detection hook (needs requestAdapter fix)
- MUST READ: `frontend/src/components/webGPUWarningBanner.tsx` — banner that uses the hook
- MUST READ: `frontend/src/components/soundControl.tsx` — quota banner pattern to follow for error surfacing
- Reference: `frontend/src/lib/voiceSelection.ts` — model constants, isServerSideModel helper
- Reference: `frontend/src/lib/browserTTS/types.ts` — worker message types
- Reference: `yapit/gateway/api/v1/audio.py` — dead code to delete

## Done When

- [ ] Synthesizer interface extracted, ServerSynthesizer and BrowserSynthesizer implementations
- [ ] All `isServerSideModel` branches removed from playbackEngine.ts
- [ ] React middleman (getPendingBrowserBlocks / onBrowserAudio / cancelBrowserBlock) removed
- [ ] Unified buffering for both modes (MIN_BUFFER_TO_START = 2)
- [ ] Worker cancel message implemented
- [ ] Voice-change no longer caches stale audio
- [ ] WebGPU detection uses requestAdapter() + isFallbackAdapter check (banner + worker)
- [ ] Error banner shown when browser TTS fails, auto-clears on model switch
- [ ] WASM fallback info shown when WebGPU unavailable but WASM works
- [ ] Dead `POST /v1/audio` endpoint deleted
- [ ] Existing tests pass, manual testing of both server and browser playback

## Considered & Rejected

- **Share cache between browser and server** — uploading browser-synthesized audio to server just to re-download adds latency, no cross-device use case worth the complexity
- **Terminate/recreate worker on voice change** — 2-5s model reload penalty is unacceptable
- **MIN_BUFFER_TO_START = 1** — insufficient stutter guard, especially for browser mode where next block can't start synthesizing until current finishes
- **Bundle Kokoro model with app** — would bloat bundle for all users including those who never use local TTS. On-demand download from HuggingFace with browser Cache API is correct.

## Discussion

- User reported issue: RTX 3080, Linux Mint 22.1, Brave (Chrome 144), NVIDIA 580.126.09. Vulkan disabled in browser, ANGLE using OpenGL. `navigator.gpu` exists (flag enabled) but `requestAdapter()` returns null. Banner hidden, local TTS silently fails.
- Brave Shields: not the default blocker we thought — tested on another Brave install, HuggingFace downloads work fine with default Shields. The `ERR_BLOCKED_BY_CLIENT` in the user's console is likely from an extension.
- Firefox: WebGPU not in stable (behind `dom.webgpu.enabled` flag). Banner correctly shows. WASM fallback works but slower.
- WASM performance: decent in Brave (with SIMD), noticeably slower in Firefox. More-than-real-time in both, so the pipeline works.
