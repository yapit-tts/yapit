---
status: active
started: 2026-01-28
---

# Frontend Performance Improvements (Tracking)

## Big Documents

Observed slowdown with 33k-block document — but only when **switching to/from the tab**, not during normal use (scrolling, playback all smooth). This suggests the issue isn't DOM count during render, but the mount/unmount cycle when React reconciles the component tree.

UPDATE (while testing PR #69), also 10k-block documents are sluggish when using the "j,k" keyboard navigation. Might be a regression from this PR, might always have been sluggish for 10k+ docs. Should be addressed, if possible.

### Explored: Virtualization

Virtualization (react-window) would render only visible blocks. Main concern: **scroll position drift**.

With variable-height blocks (measured 20-376px range, 26 unique heights in one test doc), estimated heights accumulate error. Jumping to "Chapter 15" via outliner could land blocks away from target.

**Options considered for accurate scroll position:**
- Measure-on-render with correction (slight jumpiness on first visit to region)
- Pre-measure all heights before displaying (upfront delay, then pixel-perfect)
- Hybrid threshold (only virtualize above N blocks)
- Canvas-based text measurement for better estimates

Pre-measure is appealing since large docs already have upload delay — measurement could run in that window. Batch DOM writes (single reflow) could keep it fast.

### filterVisibleBlocks O(n*m)

`filterVisibleBlocks` (`frontend/src/lib/filterVisibleBlocks.ts`) does a linear scan through sections for every audio block via `findSectionForAudioIdx`. For S sections and B blocks, this is O(S*B). Currently behind `useMemo` so not per-render, but for very large documents (1000+ pages, many sections) it could become noticeable. Fix: precomputed `audioIdx → section` map or binary search over sorted section ranges.

### Next steps
Profile actual bottleneck before committing to any approach.
