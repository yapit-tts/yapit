---
status: done
started: 2026-01-12
completed: 2026-01-12
---

# Task: Fix WebSocket voice change race condition

## Intent

When user changes voice during playback, some blocks may play with the old voice's audio. This happens because WebSocket status messages don't include voice/model info, so stale "cached" messages from the old voice can mark blocks as ready when they shouldn't be.

## The Bug

**Symptom:** User sets voice to "inworld alex", but block 51 plays with "kokoro af_heart" voice.

**Root cause:** Race condition in WebSocket message handling during voice change.

Timeline:
1. Blocks requested with kokoro voice
2. Backend processes, sends "cached" status for block 51
3. User changes voice to inworld
4. Frontend calls `ttsWS.reset()` - clears state
5. Backend's "cached" message for block 51 (kokoro) arrives AFTER reset
6. `handleMessage` sets block 51 as "cached" (no voice check)
7. Prefetch sees block 51 as "cached", skips requesting it with new voice
8. When playback reaches block 51, it fetches the cached audio URL (which is kokoro audio)

**Evidence:**
- Metrics DB shows block 51 only has kokoro variant, never synthesized with inworld
- Blocks 49, 50, 52, 53 all have inworld variants (they were properly re-requested)

## Solution

Add `model_slug` and `voice_slug` to WebSocket status messages. Frontend filters messages that don't match current voice.

### Backend Changes (yapit/gateway/api/v1/ws.py)

1. Update `WSBlockStatus` dataclass:
```python
class WSBlockStatus(BaseModel):
    type: Literal["status"] = "status"
    document_id: UUID
    block_idx: int
    status: Literal["queued", "processing", "cached", "skipped", "error"]
    audio_url: str | None = None
    error: str | None = None
    model_slug: str | None = None  # ADD
    voice_slug: str | None = None  # ADD
```

2. Update all places that send status messages to include model/voice:
   - Line ~336-342 (block not found - skipped)
   - Line ~352-359 (queued/cached response)
   - Line ~362-369 (error response)

The model/voice are available from the `model` and `voice` objects in `_handle_synthesize`.

3. Also update pubsub messages in `base.py` TTS processor (line ~182-186) - these also send status updates.

### Frontend Changes

**useTTSWebSocket.ts:**

1. Update `WSBlockStatusMessage` interface:
```typescript
interface WSBlockStatusMessage {
  type: "status";
  document_id: string;
  block_idx: number;
  status: "queued" | "processing" | "cached" | "skipped" | "error";
  audio_url?: string;
  error?: string;
  model_slug?: string;  // ADD
  voice_slug?: string;  // ADD
}
```

2. Change `blockStates` from `Map<number, BlockStatus>` to `Map<number, BlockStateEntry>`:
```typescript
interface BlockStateEntry {
  status: BlockStatus;
  model_slug?: string;
  voice_slug?: string;
  audio_url?: string;
}
```

3. Update `handleMessage` to store full entry
4. Update `getBlockStatus` to return the entry (or add new getter)

**PlaybackPage.tsx:**

1. In `triggerPrefetchBatch` (line ~736-737), filter by voice:
```typescript
const wsState = ttsWS.getBlockState(idx);
if (wsState && wsState.voice_slug === voiceSelection.voiceSlug) {
  if (wsState.status === 'cached' || wsState.status === 'queued' || ...) continue;
}
```

2. Similar check in `getBlockState` callback (line ~427-436)

3. Similar check in buffering progress calculation (line ~923-926)

## Testing

1. Start playback with kokoro voice
2. Let it buffer/play a few blocks
3. Switch to inworld voice mid-playback
4. Verify ALL blocks after the switch play with inworld voice
5. Check browser console for any "cached" messages with wrong voice being ignored

## Assumptions

- The backend always has access to model/voice when sending status messages
- Adding fields to WebSocket messages is backward compatible (frontend ignores unknown fields)

## Sources

**Code locations:**
- Backend WebSocket handler: `yapit/gateway/api/v1/ws.py:282-370`
- Backend TTS processor pubsub: `yapit/gateway/processors/tts/base.py:180-186`
- Frontend WS hook: `frontend/src/hooks/useTTSWebSocket.ts`
- Frontend prefetch logic: `frontend/src/pages/PlaybackPage.tsx:716-765`

**Diagnosis session:** Traced via metrics DB query showing block 51 missing inworld variant, and console logs showing missing status response.

## Outcome

Implemented as planned. Commit `ef6f229`.

**Verified working:** Browser logs show blocks correctly re-requested after voice switch:
- Block 51 cached with `[kokoro/af_heart]` → re-requested → cached with `[inworld/alex]`
- All status messages now include `[model/voice]` suffix for debugging
