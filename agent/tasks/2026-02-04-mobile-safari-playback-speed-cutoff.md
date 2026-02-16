---
status: done
started: 2026-02-04
---

# Task: Mobile/Safari Playback Speed > 1.0 Audio Cutoff

## Intent

User reports: "using speed faster than 1.0 will cut it off before it finishes a sentence and jump to the next. maybe a mobile or safari issue specifically?"

Audio is being cut off prematurely (before the actual audio finishes) when playbackRate > 1.0 on mobile/Safari. This means the `ended` event fires too early.

## Technical Analysis

### Audio Pipeline Architecture

```
Server path:
  WAV from server → axios fetch → audioContext.decodeAudioData → AudioBuffer

Browser path (Kokoro):
  TTS Worker → PCM (24kHz) → AudioBuffer (created with TTS sample rate)

Common path:
  AudioBuffer → WAV blob (preserves original sample rate) → blob URL → HTMLAudioElement
  HTMLAudioElement → MediaElementAudioSourceNode → GainNode → AudioContext.destination
```

### Key Code Files

- `frontend/src/lib/audio.ts` — `AudioPlayer` class
  - Uses HTMLAudioElement with `preservesPitch = true`
  - Converts AudioBuffer → WAV blob → blob URL
  - `playbackRate` set on audio element
  - "ended" event triggers callback that advances to next block

- `frontend/src/lib/playbackEngine.ts` — Playback state machine
  - `startAudioPlayback()` sets up `onEnded` callback (line 216)
  - `advanceToNext()` called when ended fires (line 218)

- `frontend/src/lib/browserSynthesizer.ts` — Browser TTS
  - Creates AudioBuffer with TTS sample rate (not AudioContext sample rate)
  - Line 61: `deps.audioContext.createBuffer(1, audio.length, msg.sampleRate)`

### Potential Root Causes

**1. Safari blob URL timing bug (WebKit Bug 238113)**
- "Audio element playback ends early when src is a blob URL"
- Occurs when blob > 65536 bytes
- Safari-specific, resolved as duplicate of 238170 (fixed)
- But the symptom there was "ended never fires" — opposite of our issue

**2. Sample rate mismatch on iOS**
- AudioContext on iOS typically runs at 44100 or 48000 Hz
- Kokoro generates audio at ~24000 Hz
- browserSynthesizer creates AudioBuffer with TTS sample rate, not AudioContext sample rate
- Known iOS issue: sample rate mismatches cause timing/distortion issues
- References: WebKit bugs #154538, #168165

**3. Safari playbackRate + blob URL interaction**
- Safari has documented bugs with playbackRate causing `currentTime` to pause for 0.1-0.3s
- Possible that with playbackRate > 1, Safari miscalculates when to fire "ended"
- The "ended" event might fire based on incorrect duration calculation

**4. MediaElementAudioSourceNode + playbackRate**
- Known WebKit bugs with choppy/glitchy audio through MediaElementAudioSourceNode
- iOS 14.5+ improved this, but timing might still be affected

## Hypotheses (Ordered by Likelihood)

1. **Sample rate mismatch causing timing issues** — Most likely for browser TTS
   - Fix: Create AudioBuffer with `audioContext.sampleRate` and resample manually
   - Or: Don't use AudioBuffer → WAV → blob flow, use AudioBufferSourceNode directly

2. **Safari blob URL timing bug** — Related to WebKit 238113/238170
   - May not be fully fixed or may have related issues with playbackRate
   - Fix: Test with data URL instead of blob URL

3. **Playback duration miscalculation with playbackRate**
   - Safari might divide duration by playbackRate somewhere incorrectly
   - Fix: Add logging to compare expected vs actual end times

## Investigation Steps

1. **Determine scope:**
   - Does it happen with server TTS (Inworld) or browser TTS (Kokoro) or both?
   - Does it happen on macOS Safari or only iOS Safari?
   - What iOS version?

2. **Add diagnostic logging:**
   - Log when "ended" fires: `currentTime`, `duration`, `playbackRate`
   - Log expected end time vs actual end time
   - Check if there's a consistent delta

3. **Test workarounds:**
   - Try using `AudioBufferSourceNode.playbackRate` instead of HTMLAudioElement
   - Try creating AudioBuffer with AudioContext sample rate
   - Try data URL instead of blob URL

## Potential Fixes

### Option A: Use AudioBufferSourceNode directly (skip HTMLAudioElement)
Pros: More direct WebAudio path, avoids blob URL issues
Cons: Major refactor of AudioPlayer, need to handle playbackRate differently

### Option B: Create AudioBuffer with AudioContext sample rate
```javascript
// In browserSynthesizer.ts
const audioBuffer = deps.audioContext.createBuffer(
  1,
  Math.round(audio.length * (deps.audioContext.sampleRate / msg.sampleRate)),
  deps.audioContext.sampleRate
);
// Resample audio into buffer
```
Pros: Fixes sample rate mismatch
Cons: Adds resampling code, may not fix the blob URL issue

### Option C: Add ended event timing workaround
```javascript
// In audio.ts, before calling onEnded
if (this.audioElement.currentTime < this.audioElement.duration * 0.95) {
  // Ended fired too early, wait for actual end
  return;
}
```
Pros: Simple workaround
Cons: Hacky, might cause other issues

### Option D: Use timeupdate event as backup
Instead of relying solely on "ended", also check `timeupdate` for when currentTime reaches duration.

## Sources

**Knowledge files:**
- [[tts-flow]] — Audio synthesis pipeline, caching, worker architecture
- [[frontend]] — React architecture, AudioContext handling, MediaSession

**External docs:**
- MUST READ: [WebKit Bug 238113](https://bugs.webkit.org/show_bug.cgi?id=238113) — Blob URL playback ends early
- MUST READ: [Howler.js iOS sample rate issue](https://github.com/goldfire/howler.js/issues/1141) — iOS AudioContext sample rate problems
- Reference: [Safari playbackRate bug report](https://www.w3.org/community/webtiming/2016/10/14/bug-report-safari-playbackrate/) — currentTime pausing issue
- Reference: [wavesurfer.js iOS Safari issue](https://github.com/katspaugh/wavesurfer.js/issues/2210) — MediaElementAudioSourceNode issues

**Key code files:**
- MUST READ: `frontend/src/lib/audio.ts` — AudioPlayer class, WAV conversion, ended event
- MUST READ: `frontend/src/lib/playbackEngine.ts` — startAudioPlayback, advanceToNext
- Reference: `frontend/src/lib/browserSynthesizer.ts` — AudioBuffer creation
- Reference: `frontend/src/hooks/usePlaybackEngine.ts` — AudioContext creation

## Discussion

Need to determine:
1. Which TTS path (browser/server) is affected?
2. Exact Safari/iOS version
3. Consistent reproduction steps (which document, which speed, etc.)

The most promising fix direction is moving away from HTMLAudioElement + blob URL toward direct AudioBufferSourceNode playback, but this is a significant refactor. A simpler first step would be to add logging to understand the exact timing discrepancy.
