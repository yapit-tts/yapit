---
status: done
started: 2026-01-04
completed: 2026-01-04
---

# Task: Retry Logic & Error Recovery

## Intent

Fix failure recovery in TTS playback. Two main issues discovered:

1. **Race condition on error retry** — block with `error` status gets re-requested, but poll loop immediately sees old `error` status and bails before server responds with `queued`

2. **Stale states after WS reconnect** — when WS disconnects and reconnects, `queued`/`processing` states persist but server has no knowledge of them. Buffer check thinks it's full, no new requests sent, blocks timeout.

Key scenario: mobile user backgrounds browser → OS suspends tab → WS disconnects → user returns → WS reconnects → playback stuck due to stale states.

## Analysis

### Current Behavior

| Failure Point | Current Handling |
|--------------|------------------|
| WS disconnect | Auto-reconnect with exponential backoff, 5 attempts max |
| Block `error` status | Re-requests (line 637), but race condition defeats it (line 656) |
| Stale `queued`/`processing` after reconnect | Nothing — buffer check counts them as "ready", no new requests |
| Audio fetch 500 | Returns null, block skipped, no retry |
| Backend worker failure | Notifies `error`, no backend retry |

### Race Condition (Bug #1)

```
PlaybackPage.tsx:
- Line 637: if status is 'error', calls ttsWS.synthesize()
- Line 656: poll loop checks if status is 'error' → returns null immediately

useTTSWebSocket.ts:
- Line 234-236: synthesize() only sets status to 'queued' if NOT already in map
- So errored blocks keep their 'error' status until server responds
```

Fix: Clear error status when re-requesting, OR skip error check for first few poll iterations after request.

### Stale States After Reconnect (Bug #2)

```
useTTSWebSocket.ts:
- Line 174-198: onclose schedules reconnect
- Line 156-166: onopen sets isConnected
- blockStates/audioUrls maps are NEVER cleared on reconnect

PlaybackPage.tsx checkAndRefillBuffer():
- Line 751-755: counts 'queued'/'processing'/'cached' as "ready ahead"
- Stale states make it think buffer is full
- No new requests, blocks eventually timeout (60s)
```

Fix: On reconnect success, clear `queued`/`processing` states (keep `cached` — audio already fetched locally).

## Proposed Fixes

### Fix 1: Race condition (frontend)

In `useTTSWebSocket.ts` `synthesize()`, unconditionally set status to `queued` when requesting:

```javascript
// Line 234-238, change from:
if (!blockStatesRef.current.has(idx)) {
  blockStatesRef.current.set(idx, 'queued');
}
// To:
blockStatesRef.current.set(idx, 'queued');  // Clear any previous error state
```

### Fix 2: Clear stale states on reconnect (frontend)

In `useTTSWebSocket.ts` `ws.onopen`, clear non-cached states:

```javascript
// After setting isConnected, before resetting reconnect attempts:
blockStatesRef.current.forEach((status, idx) => {
  if (status !== 'cached') {
    blockStatesRef.current.delete(idx);
  }
});
// Also sync to React state
```

### Not Doing

- **Backend retry on worker failure** — workers aren't flaky, frontend retry is sufficient
- **Audio fetch retry on 500** — if backend returns 500, something is broken, retry won't help
- **Backend-side reconnect protocol** — adds complexity, frontend fix is simpler

## Sources

- `frontend/src/pages/PlaybackPage.tsx` — playback logic, prefetch, buffer management
- `frontend/src/hooks/useTTSWebSocket.ts` — WS connection, state management
- `yapit/gateway/api/v1/ws.py` — backend WS handler
- `yapit/gateway/processors/tts/base.py` — job processing, error handling
- [[background-audio-mobile]] — related issue (audio stops when app backgrounded)

## Gotchas

- `blockStates` uses block `idx` as key, `audioBuffers` uses block `id` — don't confuse them
- `checkAndRefillBuffer()` counts `queued`/`processing` as "ready" — that's why stale states block new requests
- The 60s timeout (MAX_WAIT_MS) is the fallback, but users experience it as "stuck"

## Handoff

**Implemented** in `frontend/src/hooks/useTTSWebSocket.ts`:
- Fix 1: `synthesize()` now unconditionally sets status to `queued` (clears previous error)
- Fix 2: `ws.onopen` clears stale `queued`/`processing` states on reconnect

**To test** (requires backend restart to deploy):
1. Play, trigger error on a block (e.g., kill worker mid-synthesis), verify retry works
2. Play, disconnect WS (e.g., network toggle), reconnect, verify playback resumes
3. Mobile: background browser, wait for disconnect, return, verify recovery
