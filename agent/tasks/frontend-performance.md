---
status: done
started: 2025-01-05
completed: 2026-01-05
---

# Task: Frontend Performance Optimization

## Intent

Progress bar hover is noticeably laggy on documents with many blocks (600+). User expects smooth, responsive hover without visible delay.

## Observed Issue

When hovering over the progress bar on a large document:
- Visible lag/jank when moving mouse
- Especially noticeable with `SmoothProgressBar` (>200 blocks)
- Issue persists even after initial optimizations

## Quick Fixes Attempted (2025-01-05)

1. **Memoized gradient building** — `useMemo` for `buildGradient()` so it only recomputes when `blockStates`/`currentBlock` change
2. **Throttled hover updates** — Only call `setSeekPosition`/`onBlockHover` when block index changes, not every pixel

Result: User reports little to no improvement. Issue runs deeper.

## Investigation Needed

### 1. Profile the actual bottleneck
- Use React DevTools Profiler to identify what's re-rendering on hover
- Check if it's render time, commit time, or something else
- Measure with Chrome DevTools Performance tab

### 2. Suspected areas

**PlaybackPage re-renders on hover:**
- `handleBlockHover` sets `hoveredBlock` and `isDraggingProgressBar` state
- This triggers full PlaybackPage re-render
- PlaybackPage has expensive derived state computation

**Block state derivation (lines 399-423):**
```typescript
const states: BlockState[] = documentBlocks.map((block, idx) => {
  const wsStatus = isServerMode ? ttsWS.blockStates.get(idx) : undefined;
  if (cachedBlocksRef.current.has(block.id)) {
    if (audioBuffersRef.current.has(block.id) || wsStatus === 'cached') {
      return 'cached';
    }
  }
  // ... more checks
});
```
- Runs for every block (600+ iterations)
- Multiple Map lookups per block
- Currently only runs on specific dependency changes, but worth verifying

**Possible cascade:**
1. Mouse move → `setSeekPosition` in SmoothProgressBar
2. → Parent re-renders due to React reconciliation
3. → Child components re-render
4. → DOM updates

### 3. Optimization strategies to consider

**React.memo for components:**
- `SoundControl` could be memoized
- `SmoothProgressBar` / `BlockyProgressBar` could be memoized
- Need to ensure props are stable (no inline functions/objects)

**Virtualization:**
- For `BlockyProgressBar`, consider only rendering visible blocks
- For `SmoothProgressBar`, gradient approach already helps but seek indicator updates might be costly

**Debounce/throttle hover events:**
- Use `requestAnimationFrame` to batch updates
- Or lodash `throttle` with ~16ms (60fps)

**Move hover state out of React:**
- Use CSS `:hover` for visual feedback if possible
- Or use refs to update DOM directly without state changes

**Separate hover indicator from main component:**
- Extract seek position indicator to a separate component that only re-renders on position change
- Use React context or refs to avoid prop drilling

### 4. Other frontend areas to audit

- Document rendering (`StructuredDocumentView`) on large documents
- Audio buffer management (`audioBuffersRef`) with many blocks
- WebSocket message handling frequency
- Any expensive computations in render path

## Files

- `frontend/src/components/soundControl.tsx` — Progress bar components
- `frontend/src/pages/PlaybackPage.tsx` — Main playback logic, state management

## Gotchas

- `SmoothProgressBar` is used for documents with >200 blocks (SMOOTH_THRESHOLD)
- `BlockyProgressBar` renders individual divs for each block — could be even slower for large docs
- Hover triggers `onBlockHover` which scrolls the document to the hovered block — this could be expensive

## Resolution

**Root cause:** `handleBlockHover` in PlaybackPage set React state (`hoveredBlock`, `isDraggingProgressBar`) on every hover event, triggering full re-renders of the 1300-line component. The state was only used for imperative DOM updates (class manipulation + scroll).

**Fix:** Replaced `useState` with `useRef` for hover tracking. `handleBlockHover` now does direct DOM manipulation without state changes. Removed the redundant `useLayoutEffect` and `useEffect` hooks that consumed the state.

**Commit:** `6a841e3` on dev branch.
