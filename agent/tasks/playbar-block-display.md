---
status: done
started: 2026-01-03
completed: 2026-01-07
---

# Task: Playbar Block Display Layout

## Issue

The "block X of Y" display in the playbar takes away space from the progress bar, especially when TTS-1-Max is selected (longer model name). Looks messy, especially on mobile.

## Solution Implemented

Replaced the permanent "Block X of Y" display with hover-activated time/block swap:

**Default state:**
```
│ 0:00 ══════════════════════════════════════════ 57:37 │
```

**Hovering progress bar (not dragging):**
```
│   5  ══════════════════════════════════════════   42  │
    ^                                                ^
 current                                          total
 block                                           blocks
```

**Dragging progress bar:**
```
│  17  ══════════════════════════════════════════   42  │
    ^                                                ^
 target                                           total
 block                                           blocks
```

- Hovering: Left shows current playing block, right shows total blocks
- Dragging: Left shows target block (where you'd land on release), right shows total
- No tooltip — document highlighting during drag shows the target position visually

## Changes

**`frontend/src/components/soundControl.tsx`:**
- Added `isHoveringProgressBar`, `hoveredBlock`, `isDraggingProgressBar` state
- Added `handleBlockHover` wrapper to track hover state locally
- Time displays swap to block numbers when hovering progress bar
- Left display shows current block on hover, target block when dragging
- Removed tooltips from both `SmoothProgressBar` and `BlockyProgressBar`
- Removed permanent "Block X of Y" from both mobile and desktop layouts

## Benefits

- No permanent clutter — the space is freed up when not hovering
- Block info appears exactly when relevant (when interacting with playback position)
- Voice picker has room to breathe on desktop
- Mobile layout is cleaner
- During drag, you see where you'd land (left number changes to target block)
