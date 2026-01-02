---
status: active
started: 2026-01-02
---

# Task: Sidebar Edge Trigger Redesign

## Intent

**User's vision:** Replace the persistent top-left sidebar toggle button with an edge-triggered, hover-reveal mechanism. The current button feels small, far from the action, and always visible when it doesn't need to be.

**Desired behavior:**
- Invisible trigger zone along the left edge of the screen
- When cursor enters the zone, a wide-angle chevron (`‹`) fades in and slides out
- Progressive reveal: closer to center = more opaque, more "settled" in position
- On mobile: swipe-from-left-edge gesture instead of a button

**Why this might be better:**
- Cleaner UI — no persistent button cluttering the playback view
- Larger interaction area — easier to trigger than a small corner button
- Cursor doesn't have to travel to the corner — middle-of-screen is more natural
- More modern/polished feel

## Design Considerations

### Desktop Behavior

**Trigger zone:**
- Invisible rectangular area on left edge (maybe 30-50px wide, full height or middle portion?)
- Could also extend the hitbox to include the area where the chevron appears

**Reveal animation:**
- Chevron slides in from left edge (starts off-screen or very small)
- Opacity fades from 0 → 1 as cursor approaches
- Could tie animation progress to cursor X position (parallax-like) or just use CSS transition on hover

**Visual style:**
- Wide-angle chevron, not the current `PanelLeftIcon`
- Subtle, doesn't demand attention but clearly clickable when visible
- Maybe a slight backdrop blur or shadow to lift it off content

**Interaction:**
- Click to toggle sidebar (same as current)
- Or: hover for X ms to auto-open? (might be annoying)

### Mobile Behavior

**Swipe gesture:**
- Swipe from left edge to open sidebar
- Common pattern (Slack, Discord, many mobile apps)
- Need touch event handling: `touchstart` near left edge, `touchmove` tracks horizontal movement, `touchend` completes if threshold met

**Potential conflicts:**
- iOS Safari: swipe from left edge = browser back. Need to test if this can be overridden or if we need a slightly inset trigger zone
- Android: less of an issue, but worth testing

### Discoverability Concerns

New users might not know the sidebar exists if there's no visible affordance.

**Possible solutions:**
1. **First-visit tooltip** — "Swipe from the left or hover near the edge to open your documents"
2. **Subtle visual hint** — A very faint line or gradient on the left edge that hints at interactivity
3. **Pulsing hint on first load** — Chevron briefly appears and fades out to show it exists
4. **Keep button on landing page** — Only use edge trigger on playback page where clean UI matters most

### Accidental Trigger Prevention

If hitbox is too generous, users might trigger it while moving cursor across screen.

**Possible solutions:**
1. **Delay before reveal** — Cursor must be in zone for 100-200ms before chevron appears
2. **Narrow trigger zone** — 30px from edge, not 50px
3. **Only trigger on slow movement** — Fast cursor pass-through doesn't trigger
4. **Vertical constraint** — Only trigger in middle 60% of screen height, not full height

## Implementation Approach

### Phase 1: Desktop Hover Trigger
1. Create `SidebarEdgeTrigger` component
2. Position fixed on left edge with invisible hitbox
3. On mouseenter: fade in chevron with CSS transition
4. On click: call `toggleSidebar()` from sidebar context
5. On mouseleave: fade out chevron

### Phase 2: Progressive Animation (optional refinement)
1. Track cursor X position within trigger zone
2. Map X position to animation progress (opacity, translateX)
3. Smooth interpolation for natural feel

### Phase 3: Mobile Swipe
1. Add touch event listeners to detect left-edge swipe
2. Track swipe distance, show sidebar preview during swipe
3. Complete open if swipe exceeds threshold, snap back if not
4. Test on iOS Safari for back-gesture conflict

### Phase 4: Discoverability
1. Implement first-visit hint (localStorage flag)
2. Add subtle visual affordance on left edge

## Open Questions

1. **Where should this live?** Only playback page? Or app-wide?
2. **What about when sidebar is already open?** Hide the trigger? Show a close affordance on the right edge of sidebar?
3. **Hitbox size?** Need to experiment — too small = hard to find, too big = accidental triggers
4. **Animation timing?** Snappy (150ms) or smooth (300ms)?
5. **Should hover alone open the sidebar, or require a click?**

## Relevant Files

- `frontend/src/components/ui/sidebar.tsx` — Current SidebarTrigger component
- `frontend/src/layouts/SidebarLayout.tsx` — Where trigger is placed
- `frontend/src/components/documentSidebar.tsx` — The sidebar itself

## References

- macOS Dock auto-hide behavior
- Slack/Discord mobile sidebar swipe
- Many web apps with edge-triggered drawers

## Considered & Rejected

(To be filled as we explore)
