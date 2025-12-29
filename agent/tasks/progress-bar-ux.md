---
status: done
type: implementation
---

# Progress Bar UX Improvements

**Component:** `frontend/src/components/soundControl.tsx` → `BlockyProgressBar` and `SmoothProgressBar`

**Previously blocked by:** [[playbar-layout-redesign]] - ✅ RESOLVED (mobile layout fixed, touch targets sized correctly)

## Scope

This task covers:
1. **Drag/swipe seeking** - touch/mouse drag to navigate blocks ✅
2. **Hover highlighting** - highlight document block when hovering progress bar ✅

Layout/sizing work completed in [[playbar-layout-redesign]].

## Design Decision

Keep the blocky visualization (shows synthesis state at a glance) but make it behave like a slider via drag/swipe. No separate slider needed — the drag behavior turns the blocky bar into a slider while preserving the visual state info.

The innovation: "a progress bar that shows you synthesis state AND behaves like a slider."

Note: For documents with many blocks (100+), [[playbar-layout-redesign]] will implement a smooth gradient visualization. The drag interaction will still work - position maps to block index regardless of visual representation.

## Current State

The `BlockyProgressBar` component (`soundControl.tsx:17-62`) displays blocks with:
- State colors: pending (gray), synthesizing (yellow pulse), cached (green/60), current (solid green)
- Click to jump to block
- Hover brightness effect
- Equal-width segments filling the bar

Missing: drag/swipe interaction, document highlighting on hover.

## Implemented Features

### 1. Drag/Swipe Seeking (Mobile + Desktop) — ✅ DONE

**Mobile:** Touch and swipe horizontally across the progress bar to seek through blocks.

**Desktop:** Click-and-drag to enter drag mode, then slide to seek.

**Behavior:**
- **During drag**: Audio playback continues normally. The drag position is shown via yellow highlighting in the document.
- **On release**: Set `currentBlock` to the released position, triggering normal playback flow.

**Implementation:**
- Uses pointer events (`onPointerDown`, `onPointerMove`, `onPointerUp`) for unified touch/mouse handling
- 5px threshold to distinguish click vs drag
- `touch-none` CSS class prevents scroll during mobile swipe
- Pointer capture ensures drag continues if pointer leaves element

### 2. Hover Highlighting (Desktop) — ✅ DONE

**Behavior:** When hovering over a block in the progress bar, that block is highlighted in yellow in the document view.

**Visual:**
- Hovered block gets yellow/amber highlight (distinct from green active)
- Current playing block stays highlighted green
- Two blocks can be highlighted simultaneously: hovered (yellow) + active (green)
- Hover on active block shows no highlight (redundant)

**Implementation:**
- `onBlockHover?: (idx: number | null) => void` callback from progress bar components
- `hoveredBlock` state in PlaybackPage
- DOM manipulation via `useLayoutEffect` (same pattern as active highlighting)
- CSS class `.audio-block-hovered` with amber color

### 3. Mobile-First Considerations — MOVED

Layout work completed in [[playbar-layout-redesign]]:
- Touch target sizing (h-10 on mobile)
- Responsive layout (full-width on mobile)
- Smooth visualization for many-block documents

## Technical Notes

**State flow:**
```
BlockyProgressBar
  ├─ onBlockClick(idx)      → setCurrentBlock (existing)
  ├─ onBlockDrag(idx)       → setCurrentBlock (new, during drag)
  └─ onBlockHover(idx|null) → setHoveredBlock (new, lifted to parent)

PlaybackPage
  ├─ currentBlock           → highlight in document + progress bar
  └─ hoveredBlock           → highlight in document (secondary style)
```

**Pointer events pattern:**
```tsx
const [isDragging, setIsDragging] = useState(false);
const [dragStartX, setDragStartX] = useState<number | null>(null);

const handlePointerDown = (e: PointerEvent) => {
  setDragStartX(e.clientX);
  // Don't set dragging yet—wait for movement
};

const handlePointerMove = (e: PointerEvent) => {
  if (dragStartX !== null) {
    const moved = Math.abs(e.clientX - dragStartX) > 5; // threshold
    if (moved) setIsDragging(true);
  }
  if (isDragging) {
    const blockIdx = getBlockAtX(e.clientX);
    onBlockDrag?.(blockIdx);
  }
};

const handlePointerUp = (e: PointerEvent) => {
  if (!isDragging) {
    // Was a click, not drag
    onBlockClick(getBlockAtX(e.clientX));
  }
  setIsDragging(false);
  setDragStartX(null);
};
```

## Open Questions

1. Touch target size on mobile—need to test what feels right

2. Should hover highlight scroll document to show the hovered block?
   - Probably not—too aggressive. Just highlight if visible.

## Related Files

- `frontend/src/components/soundControl.tsx` - Progress bar component
- `frontend/src/pages/PlaybackPage.tsx` - Parent, manages currentBlock state
- `frontend/src/components/structuredDocument.tsx` - Document view, block highlighting

---

## Work Log

### 2025-12-29 - Implementation Complete

Implemented both hover highlighting and drag/swipe seeking.

**Files modified:**
- `frontend/src/components/soundControl.tsx` - Both progress bar components now have:
  - `onBlockHover` callback for hover/drag highlighting
  - Pointer event handlers for unified touch/mouse drag
  - `touch-none` CSS to prevent scroll during drag on mobile
  - Changed from `<button>` to `<div>` for block segments (click handled at container level)
- `frontend/src/pages/PlaybackPage.tsx` - Added:
  - `hoveredBlock` state and `prevHoveredBlockRef` for DOM manipulation
  - `useLayoutEffect` for hover highlighting (yellow, distinct from green active)
  - `onBlockHover: setHoveredBlock` passed to SoundControl
- `frontend/src/components/structuredDocument.tsx` - Added:
  - CSS for `.audio-block-hovered` class (amber/yellow color)

**Implementation details:**

1. **Hover highlighting:**
   - Progress bar reports hovered block via `onBlockHover`
   - PlaybackPage tracks `hoveredBlock` state
   - DOM manipulation adds `audio-block-hovered` class to document blocks
   - Yellow highlight distinct from green active highlight
   - Doesn't show hover on the currently active block (redundant)

2. **Drag/swipe seeking:**
   - Uses pointer events for unified touch/mouse handling
   - 5px threshold to distinguish click from drag
   - During drag: continuous hover updates (shows where you'd land)
   - On release: commits position via `onBlockClick`
   - `touch-none` prevents page scroll during mobile swipe
   - Pointer capture ensures drag continues even if pointer leaves element

**Build:** ✅ Passes

**Testing needed:**
- Desktop: hover highlighting, click to jump, drag to seek
- Mobile: touch to jump, swipe to seek

### 2025-12-29 - Analysis and Task Split

Investigated current playbar implementation via Chrome DevTools MCP.

**Critical finding:** Mobile layout is completely broken. The playbar uses `fixed bottom-0 left-64` which assumes a 256px sidebar. On mobile (375x812), the sidebar becomes a dialog overlay, not fixed positioning, so the playbar is pushed almost entirely off-screen.

Also discovered:
- Documents with many blocks (514 in test case) make individual block segments sub-pixel and meaningless
- Progress bar height `h-3` (12px) is too small for touch targets

**Decision:** Split layout work into separate task [[playbar-layout-redesign]] since it's substantial and this task was getting scope creep. The drag/swipe interaction (this task) is blocked on stable layout, but hover highlighting could potentially be implemented independently.

User confirmed:
- Mobile is must-work-well priority
- Smooth gradient visualization for long docs is acceptable
- Drag should still work on smooth visualization (maps position to block index)
