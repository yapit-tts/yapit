---
status: active
started: 2026-01-04
---

# Task: Background Audio on Mobile

## Intent

When user switches away from browser to another app on mobile, audio stops and WS disconnects. User wants audio to keep playing in background like podcast/music apps do.

Current behavior:
- Screen off → keeps playing
- Different browser tab → keeps playing
- Switch to different app → stops, WS disconnects, shows "reconnecting" or "please refresh"

## Why This Happens

Mobile OSes suspend backgrounded apps to save battery:
- Browser tab gets suspended by OS
- JS execution pauses
- WebSocket connection drops
- Audio context suspended

## Investigation Needed

- How do other web-based audio apps handle this? (Spotify web, podcast web players)
- Service Worker approach — can it keep audio alive?
- PWA with background audio permissions
- `<audio>` element tricks (sometimes keeps tab alive longer than Web Audio API)
- iOS vs Android differences
- Media Session API — we use it for controls, does it help with background?

## Sources

- [[worker-timeout-retry]] — reconnect handling helps when user returns, but doesn't solve background playback

## Gotchas

(none yet)

## Handoff

Investigate whether this is solvable for web apps or if it's an inherent platform limitation. If solvable, design approach.
