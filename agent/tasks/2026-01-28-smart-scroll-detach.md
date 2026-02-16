---
status: done
started: 2026-01-28
completed: 2026-01-28
---

# Task: Smart scroll detach with "Back to Reading" button

## Intent

Improve auto-scroll UX during playback. Previously, if user paused, scrolled up to re-read something, then resumed — it immediately snapped back to the playing block. Users wanted to temporarily detach from tracking without digging into settings.

## Solution

Implemented "smart detach" pattern (like YouTube's "Jump to live"):

1. **Detach on user scroll** — When user scrolls during active playback, auto-scroll pauses
2. **"Back to Reading" button** — Floating pill above playbar with X to dismiss
3. **Re-engage options:**
   - Click button → scroll to current block, re-attach
   - Click X → dismiss button, stay detached
   - Pause → Play while detached → button re-shows

## Implementation Details

**Key state:**
- `isScrollDetached`: whether auto-scroll is paused
- `backToReadingDismissed`: whether user clicked X
- `scrollCooldownRef`: prevents scroll events during programmatic scrolls (800ms window)

**Challenges solved:**
- Window scrolls (not the article element) — listen on `window` not container
- Programmatic scroll detection — cooldown ref blocks events during smooth scroll animations
- Double-scroll cascades — effects check cooldown before triggering new scrolls
- Stale closures — `isScrollDetached` in effect deps ensures handler recreates

**Interaction with `liveScrollTracking` setting:**
- Setting disabled = no auto-scroll at all, so no detach/button needed
- Setting enabled = smart detach behavior active

## Key Files Changed

- `frontend/src/pages/PlaybackPage.tsx` — scroll detach state, handlers, button UI
- `frontend/src/components/structuredDocument.tsx` — removed unused containerRef prop
