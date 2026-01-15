---
status: done
started: 2025-01-07
completed: 2025-01-07
---

# Task: Playback Performance Bugs - Slider Lag and Header Flickering

## Intent

User reports two bugs:

1. **Slider lag**: Volume and speed sliders are laggy when dragging - no reason for performance issues with simple range inputs
2. **Header underline flickering**: Markdown headers (which are links) flicker between underlined and non-underlined states
   - Happens when switching between local/cloud Kokoro voice
   - More pronounced when clicking play
   - Irregular pattern: slow toggle, then quick on/off bursts
   - Screenshots show "Pain Is the Only School-Teacher" header with/without underline

## Root Cause Analysis

### Slider Lag

**Cause:** No memoization of handlers or component.

When dragging the slider:
1. `handleSpeedChange`/`handleVolumeChange` (lines 1260-1265) were plain functions, NOT memoized with `useCallback`
2. Each slider tick called `setPlaybackSpeed`/`setVolume`
3. PlaybackPage (1358 lines!) re-rendered entirely
4. All unmemoized handlers recreated as new function references
5. `SoundControl` was not wrapped in `React.memo()` - re-rendered every time
6. `progressBarValues` was inline object - new reference every render

### Header Underline Flickering

**Three cascading issues:**

1. **`useTTSWebSocket` returned a new object every render** (lines 311-323):
   - Even though callbacks are memoized, the return OBJECT was new every time any state changed
   - `blockStates` and `audioUrls` change frequently during playback

2. **`handleBlockChange` depended on the entire `ttsWS` object** (line 1225):
   - Since `ttsWS` was new reference on every WS message, `handleBlockChange` recreated constantly
   - This cascaded to `handleDocumentBlockClick` → `StructuredDocumentView` re-render

3. **Dead-link effect had NO dependency array** (line 597 in structuredDocument.tsx):
   - Ran on EVERY render, toggling classes and causing visible flicker

**The cascade during playback:**
1. WS message arrives → `blockStates`/`audioUrls` update
2. `useTTSWebSocket` returns new object → `ttsWS` is new reference
3. `handleBlockChange` recreates (`ttsWS` in deps)
4. `handleDocumentBlockClick` recreates (depends on `handleBlockChange`)
5. `StructuredDocumentView` receives new `onBlockClick` prop → re-renders
6. Dead-link effect runs (no deps) → classes toggled

## Fixes Applied

### 1. `useTTSWebSocket.ts`
- Added `useMemo` to imports
- Wrapped return object with `useMemo` so reference is stable when values don't change

### 2. `PlaybackPage.tsx`
- Changed `handleBlockChange` to depend on `ttsWS.moveCursor` (stable callback) instead of `ttsWS` (object)
- Memoized `handleVolumeChange` and `handleSpeedChange` with `useCallback`
- Added `useMemo` for `progressBarValues` object
- Updated `SoundControl` to use memoized `progressBarValues`

### 3. `structuredDocument.tsx`
- Added `[doc]` dependency array to the dead-link effect (was missing, ran every render)

### 4. `soundControl.tsx`
- Added `memo` to imports
- Wrapped `SoundControl` with `React.memo()`

## Gotchas

- `useTTSWebSocket` returning a plain object causes ALL consumers to recreate callbacks when ANY state changes
- Missing dependency array on useEffect = runs every render = performance disaster
- Using entire hook return object in callback deps cascades updates even when you only need one function

## Handoff

Fixes implemented. TypeScript check passes. Need user to:
1. Restart backend with `make dev-cpu`
2. Test slider dragging - should be smooth now
3. Test voice switching and playback - headers should not flicker
