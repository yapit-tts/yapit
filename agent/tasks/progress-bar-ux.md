---
status: blocked
type: implementation
---

# Progress Bar UX Improvements

**Component:** `frontend/src/components/soundControl.tsx` → `BlockyProgressBar`

**Blocked by:** [[playbar-layout-redesign]] - mobile layout is completely broken, need stable responsive foundation before adding interactions

## Scope

This task covers:
1. **Drag/swipe seeking** - touch/mouse drag to navigate blocks (blocked)
2. **Hover highlighting** - highlight document block when hovering progress bar (can implement independently)

Layout/sizing work has been moved to [[playbar-layout-redesign]].

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

## Planned Improvements

### 1. Drag/Swipe Seeking (Mobile + Desktop) — BLOCKED

**Mobile:** Touch and swipe horizontally across the progress bar to seek through blocks. Like a slider in video games.

**Desktop:** Long-press (or just click-and-drag) to enter drag mode, then slide to seek.

**Behavior:**
- **During drag**: Audio playback continues normally (if playing block 5, keeps playing block 5). The drag position is purely visual—shown in progress bar + highlighted in document—but doesn't change `currentBlock` until release. No new synthesis requests during drag.
- **On release**: Set `currentBlock` to the released position. This triggers normal playback flow (synthesis if not cached, playback if cached). Existing eviction logic handles any in-flight requests from old position.

Essentially: drag for visual exploration ("where do I want to jump to?"), release to commit. Power user feature for efficient navigation, especially satisfying on mobile.

**Implementation considerations:**
- Use `onPointerDown`, `onPointerMove`, `onPointerUp` for unified touch/mouse handling
- Track drag state to distinguish click vs drag
- Consider debouncing the `setCurrentBlock` calls during drag (or maybe not—instant feedback might be better)
- Might need to prevent default touch scrolling while dragging on mobile

### 2. Hover Highlighting (Desktop)

**Behavior:** When hovering over a block in the progress bar, highlight that block in the document view (not just the progress bar).

**Visual:**
- Hovered block in document gets a subtle highlight (could be same green as current, or a different accent like yellow)
- Doesn't snap playback to that block—just visual preview
- Current playing block stays highlighted with its normal treatment
- Two blocks can be highlighted simultaneously: hovered + current

**Implementation:**
- Need to lift hover state up to parent (or use context) so document view can access it
- Add `hoveredBlock` state alongside `currentBlock`
- `BlockyProgressBar` reports hover via `onBlockHover?: (idx: number | null) => void`
- Document view applies highlight style to `hoveredBlock`

**Color options:**
- Same green for both (simpler, less visual noise)
- Different color for hover (yellow?) to distinguish from "currently playing"
- Start with same green, see if distinction is needed

### 3. Mobile-First Considerations — MOVED

Moved to [[playbar-layout-redesign]]:
- Touch target sizing
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
