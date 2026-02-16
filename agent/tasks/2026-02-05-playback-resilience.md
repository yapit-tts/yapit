---
status: done
started: 2026-02-05
---

# Task: Audio Playback Resilience — Fix Silent Failures and Add Retry/Recovery

## Intent

Audio playback often requires refreshing (sometimes twice) on mobile. Two symptom variants:

1. **"Have to refresh"**: Engine enters `buffering` and hangs forever because WS wasn't connected when first synthesis fired — all `synthesize()` calls return null silently.
2. **"Playing but no sound"**: `HTMLAudioElement.play()` throws `NotAllowedError` (mobile gesture expired), error is swallowed, engine thinks it's playing.

Root cause: the system has zero resilience to timing gaps or missed messages. The happy path works; any disruption creates permanent silent hangs.

## Design Principles

1. **Pubsub is an optimization, not the mechanism.** `synthesize` is already idempotent (check cache → check inflight → queue). Re-sending it is the recovery mechanism.
2. **Client owns retry responsibility.** Server is stateless per-connection.
3. **Every async operation has a timeout and error path.** No silent hangs.
4. **User gestures handled explicitly.** Audio element unlocked at gesture time, before async work.

## Implementation (logical dependency order)

### 1. AudioPlayer resilience (`audio.ts`)
- `unlock()` method: plays silent WAV on the audio element in gesture context → element "blessed" for future programmatic play
- `load()`: add `error` event listener → reject. Add timeout (5s) → reject.
- `play()`: propagate errors instead of swallowing

### 2. Playback engine error handling (`playbackEngine.ts`)
- `startAudioPlayback()`: handle play() rejection → retry once, then skip to next block

### 3. Fix playWithResume wrapper + audio unlock (`usePlaybackEngine.ts`)
- Store original play in a ref set once (not every render)
- New wrapper: unlock() + AudioContext.resume() + original play
- No more compounding wrapper chain

### 4. Server synthesizer retry (`serverSynthesizer.ts`)
- On timeout: retry synthesis request instead of resolving null
- Track pending requests for reconnect recovery
- `retryPending()` method for WS reconnect to call

### 5. WebSocket connection queue (`useTTSWebSocket.ts`)
- Queue messages when not connected, drain on connect
- `onReconnect` callback so synthesizer can re-send pending requests

### 6. Backend hardening (`ws.py`)
- Pubsub listener: catch all exceptions, restart loop (only stop on WS disconnect)
- Message handlers: broad try/except so one bad message doesn't kill connection
- WS keepalive: periodic ping for half-open connection detection

## Assumptions

- Audio element unlock via silent WAV play is sufficient for iOS Safari and Chrome mobile (standard pattern used by game engines, Howler.js, etc.)
- `synthesize` WS message remains idempotent — safe to retry
- Buffering timeout values are tunable; starting with generous defaults

## Sources

**Knowledge files:**
- [[tts-flow]] — full synthesis pipeline, WebSocket protocol, worker architecture
- [[frontend]] — playback engine architecture, AudioContext handling, audio output

**Key code files:**
- MUST READ: `frontend/src/lib/audio.ts` — AudioPlayer, where play/load happen
- MUST READ: `frontend/src/lib/playbackEngine.ts` — state machine
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — React bridge, wrapper bug
- MUST READ: `frontend/src/lib/serverSynthesizer.ts` — WS synthesis, pending tracking
- MUST READ: `frontend/src/hooks/useTTSWebSocket.ts` — connection management
- MUST READ: `yapit/gateway/api/v1/ws.py` — server WS handler, pubsub listener

## Done When

- [ ] First play works reliably on mobile without refresh
- [ ] No "playing but silent" state possible
- [ ] WS disconnection + reconnection recovers gracefully
- [ ] No infinite buffering — all hangs have timeouts with user-visible feedback
- [ ] Backend pubsub listener doesn't silently die

## Considered & Rejected

- **Full protocol redesign with sync endpoint**: Unnecessary — `synthesize` is already idempotent and serves as sync mechanism
- **HTTP polling fallback**: Adds complexity for marginal benefit when WS retry covers the same cases
- **Inflight key reordering in result_consumer**: Investigated — current "delete first" pattern is correct. Atomic delete() return value is the dedup mechanism preventing double-billing. Moving to end would break dedup or create liveness issues. Self-heals on failure.
- **Buffering timeout as UI feature**: Spinner is sufficient feedback. Infinite hangs fixed at mechanism level (synthesis retry + WS reconnect). Existing WASM banner covers slow browser TTS. No separate timeout needed.
