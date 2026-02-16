---
status: done
started: 2026-02-02
---

# Task: MediaSession Metadata & Mobile Lock Screen Controls

## Intent

Users on mobile see "Unknown Artist" / no useful info in lock screen / dynamic island / notification media controls. The MediaSession action handlers are already wired (play/pause/skip) in `PlaybackPage.tsx:440-460`, but **no metadata is set** — no title, no artist, no artwork, no position state.

Goal: When playing a document, the OS media controls should show:
- **Title** = document title
- **Artist** = "Yapit" (or leave blank — avoid "Unknown Artist")
- **Artwork** = Yapit logo (optional, nice-to-have)
- **Progress bar** working via `setPositionState`

This also fixes the desktop Linux media widget (screenshot from friend's NixOS setup showing "Unknown Artist").

## Assumptions

- `navigator.mediaSession.metadata` just needs to be set with a `MediaMetadata` object — the browser handles the rest (lock screen, dynamic island, notification shade)
- Document title is available in `PlaybackPage` (from `useParams` / document data)
- `setPositionState` needs duration + position + playbackRate — we have all of these from `AudioPlayer` and playback engine state
- The `HTMLAudioElement` in `AudioPlayer` (`audio.ts:31`) is what triggers the browser's media session — since it's routed through `AudioContext` via `createMediaElementSource`, the browser should still pick it up for MediaSession

## Sources

**Knowledge files:**
- [[frontend]] — Playback engine architecture, MediaSession mention, key files
- [[tts-flow]] — Audio pipeline, how blocks become audio

**Key code files:**
- MUST READ: `frontend/src/pages/PlaybackPage.tsx` — MediaSession handlers at ~L440, document metadata available
- MUST READ: `frontend/src/lib/audio.ts` — AudioPlayer, has duration/progress/tempo info
- MUST READ: `frontend/src/hooks/usePlaybackEngine.ts` — React bridge, AudioContext creation
- Reference: `frontend/src/lib/playbackEngine.ts` — state machine, block index tracking

**External docs:**
- Reference: [MDN MediaSession API](https://developer.mozilla.org/en-US/docs/Web/API/MediaSession) — metadata, setPositionState, artwork

## Done When

- [ ] Document title shown in OS media controls instead of "Unknown Artist"
- [ ] `setPositionState` updates so progress bar works in OS controls (currently empty/non-functional)
- [ ] Skip forward/back buttons visible in OS media controls (handlers exist but buttons don't render — likely because no metadata/position state is set)
- [ ] Tested on mobile (iOS Safari, Android Chrome) via DevTools resize + manual

## Implementation Notes

Straightforward — two additions to the existing MediaSession `useEffect` in PlaybackPage:

1. **Set metadata** when document loads / title changes:
   ```ts
   navigator.mediaSession.metadata = new MediaMetadata({
     title: documentTitle,
     artist: "Yapit",
     // artwork: [{ src: "/logo.png", sizes: "512x512", type: "image/png" }]
   });
   ```

2. **Update position state** on progress callback or block change:
   ```ts
   navigator.mediaSession.setPositionState({
     duration: totalDurationSec,
     playbackRate: tempo,
     position: currentPositionSec,
   });
   ```

   Challenge: we track per-block progress, not total document progress. May need to compute total from block durations. Could start simple (per-block duration) and improve later.

## Browser Findings

- **iOS Safari/Chrome**: Full MediaSession support — title, artist, artwork, progress bar, skip buttons all work ✅
- **Firefox Android**: Metadata (title/artist) works. Skip buttons and progress bar do NOT render — known Firefox Android limitation, not fixable on our end.
- **Chrome Android**: Entire page layout is broken (wrong scale, requires extreme zoom-out, controls unreachable). Pre-existing issue, unrelated to MediaSession. Needs separate investigation — likely viewport meta tag or CSS layout issue.

## Transient Audio Bug (Unresolved)

From Discord: "clicked play, refreshed, made sure everything unmuted, but neither stopping and playing or anything worked. Play button was in playing mode but didn't progress or make any sound. Mobile. Checked 1h later and it worked again."

**Possible causes:**
- `AudioContext` stuck in "suspended" state — mobile browsers require user gesture to resume. If the gesture check (`usePlaybackEngine.ts:132`) fails silently, audio won't play but UI might still show "playing"
- WebSocket disconnected silently — blocks never get synthesized, engine waits forever
- `createMediaElementSource` can only be called once per element — if somehow the AudioPlayer gets re-created without a new element, this throws and audio silently fails

**Not enough data to fix.** Will keep an eye out during implementation. If the AudioContext resume path has any edge cases, we might catch it.
