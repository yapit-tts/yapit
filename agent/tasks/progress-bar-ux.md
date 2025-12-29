---
status: active
type: implementation
---

# Progress Bar UX Improvements

**Component:** `frontend/src/components/soundControl.tsx` → `BlockyProgressBar`

## Design Decision

Keep the blocky visualization (shows synthesis state at a glance) but make it behave like a slider via drag/swipe. No separate slider needed — the drag behavior turns the blocky bar into a slider while preserving the visual state info.

The innovation: "a progress bar that shows you synthesis state AND behaves like a slider."

## Current State

The `BlockyProgressBar` component (`soundControl.tsx:17-62`) displays blocks with:
- State colors: pending (gray), synthesizing (yellow pulse), cached (green/60), current (solid green)
- Click to jump to block
- Hover brightness effect
- Equal-width segments filling the bar

Missing: drag/swipe interaction, document highlighting on hover.

## Planned Improvements

### 1. Drag/Swipe Seeking (Mobile + Desktop)

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
- the pbar needs to be slightly larger anyways, not just for mobile (Then bigger docs are also much less of an issue)
 - and this task is a good opportunity to also encompass yk maybe a full visual redesign of the playbar section? hm, maybe not. prlly better to make that a separate task? unless it's important to think it holistically, yk with how we do mobile etc. and proper responsive layout and like yk reposition some of the audio controls / redesign a bit - should maybe brainstorma and create prototypes before we implement this feature !

**Implementation:**
- Need to lift hover state up to parent (or use context) so document view can access it
- Add `hoveredBlock` state alongside `currentBlock`
- `BlockyProgressBar` reports hover via `onBlockHover?: (idx: number | null) => void`
- Document view applies highlight style to `hoveredBlock`

**Color options:**
- Same green for both (simpler, less visual noise)
- Different color for hover (yellow?) to distinguish from "currently playing"
- Start with same green, see if distinction is needed

### 3. Mobile-First Considerations

- Progress bar needs adequate touch target height on mobile (currently `h-3`, might need `h-4` or larger on mobile)
- Consider full-width on mobile (currently constrained by `max-w-2xl`)
- Swipe gesture should feel native and responsive

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
