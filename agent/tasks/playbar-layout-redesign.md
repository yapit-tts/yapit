---
status: done
type: implementation
---

# Playbar Layout Redesign

**Blocking:** [[progress-bar-ux]] - drag/swipe interaction depends on stable layout

## Goal

Fix the fundamentally broken responsive layout of the playbar component, making mobile a first-class experience while improving desktop as well.

## Current Problems

1. **Mobile completely broken** - `fixed bottom-0 left-64 right-0` assumes 256px sidebar always exists. On mobile, sidebar is a dialog overlay, so playbar is pushed off-screen.

2. **Sidebar overlap issue** - When sidebar expands on desktop, it covers document content and header buttons instead of the content area resizing properly. Same root cause: hardcoded positioning not responding to sidebar state.

3. **Progress bar meaningless with many blocks** - Documents with 100+ blocks result in sub-pixel segments. A 514-block document shows just noise.

4. **Progress bar too small for touch** - `h-3` (12px) is inadequate. Apple recommends 44px minimum touch targets.

5. **Controls cramped on narrow screens** - Speed slider, volume slider, and settings button squeeze together.

## Design Decisions

- Mobile is a must-work-well priority
- Smooth gradient visualization for documents with **>200 blocks**
- Drag/swipe interaction will still work on smooth visualization (position maps to block index)
- Block-precise navigation available via skip forward/back buttons

### Layout Approach

**Desktop (stacked rows, sidebar-aware):**
```
┌─────────────────────────────────────────────────┐
│         [⏮] [▶] [⏭]                            │
│  0:00 ════════════════════════════════ 57:37   │
│  Voice ▼    Block 1/514    1.0x ═══  🔊═══ ⚙   │
└─────────────────────────────────────────────────┘
```
- Playbar and content area both respond to sidebar state
- No more hardcoded `left-64`

**Mobile (expandable):**
```
Collapsed (default):
┌───────────────────────────┐
│ 0:00 ════════════════ 57:37│  <- taller bar
│       [⏮] [▶] [⏭]        │
└───────────────────────────┘

Expanded (tap chevron/swipe up):
┌───────────────────────────┐
│ 0:00 ════════════════ 57:37│
│       [⏮] [▶] [⏭]        │
│ ─────────────────────────  │
│ Voice: Kokoro · Heart    ▼ │
│ Speed: 1.0x    ════════    │
│ Volume         ════════    │
└───────────────────────────┘
```

### Smooth Mode Visualization (>200 blocks)
```
┌────────────────────────────────────────┐
│▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░│
│ cached     │current    pending        │
│ (green)    │(bright)   (gray)         │
└────────────────────────────────────────┘
```
- CSS gradient with color stops at block boundaries
- Position indicator for current block
- Drag preview shows where you'd land

## Next Steps

1. ~~Fix responsive positioning - make playbar + content respond to sidebar state~~ ✅ Done
2. ~~Increase progress bar touch target size~~ ✅ Done
3. ~~Implement expandable mobile layout~~ ✅ Done
4. ~~Implement smooth visualization mode for >200 block documents~~ ✅ Done

All layout items complete. Remaining work for drag/swipe interactions is tracked in [[progress-bar-ux]].

## Open Questions

1. Should the smooth visualization show exact block boundaries on hover/during drag? (probably yes, as a tooltip or small indicator)

## Related Files

- `frontend/src/components/soundControl.tsx` - Main component, `BlockyProgressBar` at lines 17-62
- `frontend/src/pages/PlaybackPage.tsx` - Parent, manages state
- `frontend/src/layouts/SidebarLayout.tsx` - Sidebar provider
- `frontend/src/components/ui/sidebar.tsx` - Sidebar component with width info

## Notes / Findings

### Current Layout Structure (soundControl.tsx:144)

```tsx
<div className="fixed bottom-0 left-64 right-0 bg-background/80 backdrop-blur-lg border-t border-border p-4">
```

The `left-64` (256px) is the problem - it's hardcoded assuming sidebar is always visible and expanded.

### Sidebar Behavior

From `SidebarLayout.tsx` and `documentSidebar.tsx`:
- Uses shadcn/ui Sidebar component
- On desktop: sidebar is fixed, ~256px wide when expanded
- On mobile: sidebar becomes a dialog overlay (not fixed positioning)
- Need to detect sidebar state or use CSS approach

### Progress Bar Visualization

Current (BlockyProgressBar):
- Equal-width flex segments filling container
- Colors: gray (pending), yellow pulse (synthesizing), green/60 (cached), solid green (current)
- Each segment is a `<button>` with click handler

For smooth mode:
- Could use CSS gradient with color stops at block boundaries
- Or canvas/SVG for more control
- Interaction: calculate block index from x position relative to bar width

---

## Work Log

### 2025-12-29 - Remaining Layout Items Complete

**What was done:**

1. **Touch target size** - Progress bar height increased from `h-3` (12px) to `h-10` (40px) on mobile, `h-5` (20px) on desktop. Applied to both `BlockyProgressBar` and new `SmoothProgressBar`.

2. **Expandable mobile layout** - On mobile, the playbar now shows collapsed by default:
   - Collapsed: controls + progress bar + "Block X of Y" + chevron
   - Expanded: adds voice picker, speed slider, volume slider, settings
   - Chevron rotates 180° when expanded
   - Desktop always shows full horizontal layout (unchanged)

3. **Smooth gradient visualization** - For documents with >200 blocks (SMOOTH_THRESHOLD):
   - CSS gradient with color stops at block boundaries
   - Position indicator (thin vertical line) for current block
   - Click-to-seek still works (maps x position to block index)
   - State colors: pending (muted), synthesizing (yellow), cached (primary/60), current (primary)

**Files modified:**
- `frontend/src/components/soundControl.tsx`:
  - Added `SmoothProgressBar` component (lines 21-97)
  - Added `SMOOTH_THRESHOLD = 200` constant
  - Updated `BlockyProgressBar` height classes
  - Added `isMobileExpanded` state and conditional rendering for mobile/desktop layouts
  - Added `ChevronUp` icon import

**Verified with Chrome DevTools MCP:**
- ✅ Mobile (375x812): Taller progress bar, collapsed layout, chevron expands to show voice/speed/volume
- ✅ Desktop: Full horizontal layout unchanged
- ✅ 331-block document uses SmoothProgressBar with gradient + position indicator

**Status:** Layout items implemented, but smooth gradient had a bug (see below)

### 2025-12-29 - Gradient Bug Fix

Initial `SmoothProgressBar` gradient was transparent because of invalid CSS syntax:
- ❌ `oklch(var(--primary))` - wrong, var already contains full `oklch(...)` value
- ✅ `var(--primary)` - correct for solid colors
- ✅ `color-mix(in oklch, var(--primary) 60%, transparent)` - correct for opacity

Fixed in `soundControl.tsx:44-48`.

### 2025-12-29 - Responsive Positioning Implemented

**What was done:**
- Added `useSidebar()` hook to soundControl.tsx
- Playbar now uses dynamic left positioning:
  - `left-0` when mobile OR sidebar collapsed
  - `left-[var(--sidebar-width)]` when desktop with expanded sidebar
- Added smooth transition for the left offset

**Files modified:**
- `frontend/src/components/soundControl.tsx` - lines 8, 134, 147-153 (playbar positioning)
- `frontend/src/layouts/SidebarLayout.tsx` - line 8: `w-full` → `flex-1 min-w-0` (content area sizing)

**Status:** ✅ Step 1 complete - responsive positioning fixed

**Verified (with Chrome DevTools MCP):**
1. ✅ Desktop expanded sidebar - playbar offset by sidebar width
2. ✅ Desktop collapsed sidebar - playbar full width (left-0)
3. ✅ Mobile (375x812) - playbar full width, visible and functional
4. ✅ Smooth transition animation on sidebar toggle
5. ✅ Header buttons (copy/download/export) now visible - content area respects sidebar width

**Both fixes:**
- Playbar: Dynamic `left` positioning via `useSidebar()` hook
- Content area: Changed from `w-full` (100vw) to `flex-1 min-w-0` (remaining space)

### 2025-12-29 - Task Created

Created from analysis during [[progress-bar-ux]] investigation.

Screenshots taken showing:
- Desktop view (1280x800): playbar visible but progress bar thin, controls cramped
- Mobile view (375x812): playbar almost entirely off-screen due to `left-64`

Key insight: This isn't just a "make it bigger" fix. The entire positioning strategy is broken for responsive layout. Need to:
1. Use sidebar-aware positioning (CSS variables or context)
2. Rethink control layout for mobile
3. Add adaptive visualization mode for different block counts
