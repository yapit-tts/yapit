---
status: active
started: 2026-01-03
---

# Task: Cross-Device Sync

Current state: playback position and starred voices are localStorage only.

## What to Sync

- **Playback position** — resume where you left off on another device
- **Starred voices** — voice picker favorites

## Considerations

- Needs backend storage (user preferences table?)
- Sync strategy: on change? periodic? on app focus?
- Conflict resolution if edited on multiple devices

## Priority

Nice-to-have UX improvement, not critical for launch.
