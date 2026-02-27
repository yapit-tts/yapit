---
status: active
started: 2026-01-28
refs:
  - agent/tasks/2026-02-26-frontend-perf-infra.md
---

# Frontend Performance Improvements (Tracking)

## Problem

10k+ block documents are sluggish during j/k navigation and outliner interaction. 33k-block documents are additionally slow on tab switch (mount/unmount).

## Completed: JS Hot Path Fixes (ff31005)

Benchmarking infrastructure: `perfMonitor.ts` exposes `window.__yapit_perf` in dev for agent-driven measurement. Fixture documents seeded via `scripts/seed_perf_fixtures.py` (6 sizes × 3 variants). Temporary — remove after perf work is done.

### deriveBlockStates caching

Was recomputed on every `getSnapshot()` (10x/sec during playback), iterating all blocks with 3 Map lookups each. Now cached with version counter, invalidated only when `audioCache`/`knownCached`/`synthesisPromises` mutate.

| Document | Before | After |
|---|---|---|
| flat 10000b (j/k) | 1.75ms avg, 3.2ms p95 | 0ms (cached) |
| dense 10000b (j/k) | 1.97ms avg, 3.9ms p95 | 0ms (cached) |

### filterVisibleBlocks O(n*m) → O(n)

Replaced `sections.find()` per audio block with precomputed `Map<audioIdx, Section>`.

| Document | Before | After |
|---|---|---|
| sectioned 5000b | 3.0ms avg | 0.9ms avg (3.3x) |
| dense 10000b | 12.4ms | 2.05ms avg (6x) |

## Completed: Decouple StructuredDocumentView from Cursor (a2b70e9)

Root cause of perceived j/k sluggishness: `StructuredDocumentView` (5-10k DOM nodes) re-rendered on every cursor change because it received `currentBlockIdx` as a prop. Its only use was a collapse guard ("don't collapse section containing current block") that only matters at click time.

Fix: replaced with a stable `canCollapseSection` callback that reads `currentBlock` from a ref at click-time. StructuredDocumentView now has **zero re-renders on j/k navigation** (was 1 per keypress).

User feedback: j/k "noticeably smoother, acceptable for such a big document." Outliner interaction "imperceptible."

## Completed: PlaybackPage split + progress tick elimination

### PlaybackOverlay extraction

PlaybackPage (~850 lines) subscribed to `useSyncExternalStore` for engine snapshots, causing all ~25 hooks and the full JSX tree to re-evaluate on every cursor change — even though the heavy child (`StructuredDocumentView`, 5-10k DOM nodes) was memo'd.

Split into:
- **PlaybackPage** (static shell, ~360 lines) — document fetching, settings, keyboard handler, `StructuredDocumentView`. No snapshot subscription. Re-renders only on doc load, settings changes, section toggles.
- **PlaybackOverlay** (~250 lines) — owns the snapshot subscription. DOM highlighting, scroll tracking, position save, MediaSession state, progress bar, SoundControl, DocumentOutliner, "Back to Reading" pill.

Communication via 3 ref bridges (overlay writes, shell reads): `scrollToBlockRef`, `currentBlockRef`, `handleBackToReadingRef`.

### Audio progress notify() removal

The engine's audio progress callback called `notify()` on every audio player tick (~30-60Hz during playback), triggering full React re-renders for a time display that only visually changes at block boundaries. Removed `notify()` from the progress callback — engine still tracks `audioProgress` internally for on-demand reads (MediaSession, future smooth display), but no longer drives re-renders.

### Measurements (dense 10000b, 12k blocks, 48k DOM nodes)

| Metric | Before split | After split |
|---|---|---|
| JS processing per j/k | ~15ms | **2.5ms** |
| PlaybackPage re-renders per j/k | 1 | **0** |
| PlaybackOverlay re-renders per j/k | n/a | 1 |
| Re-renders during playback (idle) | ~30-60/sec | **0** (progress tick removed) |

Total interaction time (through paint) is ~193ms on the 48k-node document, but ~190ms of that is browser layout/paint — not JS.

## Remaining: Browser Layout/Paint Cost

On 48k DOM node documents, the browser's style recalc + paint from the `classList` toggle dominates (~190ms). This is not a React problem.

Potential approaches (not yet attempted):
1. **`content-visibility: auto`** — CSS property to skip rendering off-screen elements. Biggest potential win, no React changes.
2. **Replace `querySelectorAll` with element index** — `findElementsByAudioIdx` scans 48k nodes per call. A `Map<number, Element>` built during render would be O(1).
3. **CSS `contain`** on section containers — limits style recalc scope.
4. **Virtualization** — only render visible blocks. Hard due to variable-height blocks (20-376px). Last resort.

## Open: Initial Load / Tab Switch

33k-block documents are slow on mount (initial render or tab switch). This is the React mount cost for the full DOM tree. Only real fix is virtualization, which has a hard scroll-position-drift problem with variable-height blocks (20-376px range). Deferred — less impactful than interaction performance since it's a one-time cost.
