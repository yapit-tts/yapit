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
| PlaybackPage re-renders per j/k | 1 | **0** |
| PlaybackOverlay re-renders per j/k | n/a | 1 |
| Re-renders during playback (idle) | ~30-60/sec | **0** (progress tick removed) |

## Deep Profiling: Where the Time Actually Goes

Previous sessions reported "2.5ms JS processing" per j/k. This was wrong — it only measured the synchronous event handler. A thorough decomposition (2026-02-27) revealed the true breakdown on `[perf] dense 10000b` (12k blocks, 48k DOM):

### Methodology

1. **2×rAF total cost**: dispatch keydown → `requestAnimationFrame` × 2 → `performance.now()` delta. Captures everything: JS, React render, effects, browser style recalc, layout, paint.
2. **Component render timing**: `performance.now()` at start/end of PlaybackOverlay, SoundControl, SmoothProgressBar function bodies. Captures hook evaluation + JSX creation for each component.
3. **Effect timing**: `performance.now()` around the classList toggle `useLayoutEffect`.
4. **Isolation tests**: monkey-patched `Element.prototype.scrollIntoView`, `DOMTokenList.prototype.add/remove` to no-ops to isolate specific costs.
5. **CSS experiments**: injected `<style>` to test `transition: none`, `contain: layout style paint`, `:has()` rule removal.

Previous agents used only method 1 and misattributed the cost. The 2×rAF measurement mixes JS, React, and browser paint into one number. Methods 2-5 decompose it.

### Results

| Layer | Cost | Method |
|---|---|---|
| Overlay render (all hooks + JSX) | **0.1ms** | Component timing |
| SoundControl render (memo'd, all hooks) | **0ms** | Component timing |
| SmoothProgressBar render + gradient | **0ms** | Component timing (gradient useMemo holds — blockStates ref is stable during j/k) |
| classList highlight effect | **3ms** | Effect timing |
| scrollIntoView | **~25ms** | Isolation (median 102→76 without it) |
| **Total JS** | **~3ms** | Sum of component + effect timing |
| **Total interaction (2×rAF)** | **75ms median** | 2×rAF measurement |
| **Browser style recalc + paint** | **~72ms** | Total minus JS |
| Periodic spikes (GC/compositor) | **~300ms** | Observed in ~30% of presses, consistent across all configurations |

### Key finding: React is already free

The previous plan to optimize React reconciliation (decouple gradient from currentBlock, memo DocumentOutliner, split useFilteredPlayback) was targeting <1ms of total cost. All React render functions complete in <0.1ms:

- The SmoothProgressBar gradient useMemo's deps are `[blockStates, currentBlock, numBlocks]`, but `blockStates` is reference-stable during j/k (engine caches the array via `blockStatesVersion`). The gradient only rebuilds when synthesis state changes, not on cursor moves. The `currentBlock` dep causes a new gradient string, but the computation is fast for this doc size.
- SoundControl's memo is technically busted (new `progressBarValues` object each render), but its render is 0ms — all hooks return cached values.
- useFilteredPlayback recomputes on `currentBlock` change, but its `perfMonitor` instrumentation showed ~0ms.

### CSS experiments: no help

| Configuration | Median | Notes |
|---|---|---|
| Baseline | 77ms | |
| `transition: none !important` on all blocks | 76ms | No effect — transitions only on color, not geometry |
| `+ contain: layout style paint` on container | 75ms | Negligible — the container is the full page |
| `+ :has()` rules removed | Similar | `:has(.audio-block-active)` invalidation cost is minimal |
| No classList toggle at all | 67ms | Only ~10ms from the class toggle itself |
| No scrollIntoView at all | 76ms (from 102) | scrollIntoView forces synchronous layout |
| No classList AND no scrollIntoView | 67ms | Irreducible: React commit + browser frame |
| No interaction (pure rAF baseline) | 16ms | Normal 60fps frame |

The ~50ms above the 16ms rAF baseline, even with all DOM mutations disabled, is React's commit phase (fiber tree walk, effect scheduling, DOM reconciliation for the overlay's ~300 nodes) plus browser frame overhead on a 48k-node page.

## Remaining: Browser Layout/Paint Cost

The 75ms median (spikes to 300ms) is dominated by browser work on 48k DOM nodes. This is not a JS or React problem — it's the cost of the browser processing a huge DOM tree.

### Attempted and rejected

- **CSS `content-visibility: auto`** on blocks — made things worse (523ms). Browser's visibility recalculation when toggling classes on `content-visibility: auto` elements is more expensive than the baseline.
- **CSS `contain: layout style paint`** — <5ms improvement, not meaningful.
- **`querySelectorAll` → Map lookup** — saves ~2.4ms, but adds complexity (Map must stay in sync with section collapse/expand). Not worth it for the savings.
- **Removing CSS transitions** — no effect (transitions are color-only, not geometry).
- **React optimizations (gradient, memo, hook splitting)** — would save <1ms. React render is already 0.1ms.

### Path forward: virtualization

The only approach that can meaningfully reduce the 75ms is rendering fewer DOM nodes. Options:
1. **Windowed rendering** — only render blocks within/near the viewport. Would reduce 48k nodes to ~100-200. Major architectural change. Hard problem: variable-height blocks (20-376px) make scroll position estimation imprecise.
2. **Section-level lazy rendering** — collapsed sections already don't render their blocks. Could extend this to off-screen sections. Simpler than full virtualization but coarser-grained.

## Open: Initial Load / Tab Switch

33k-block documents are slow on mount (initial render or tab switch). This is the React mount cost for the full DOM tree. Only real fix is virtualization, which has a hard scroll-position-drift problem with variable-height blocks (20-376px range). Deferred — less impactful than interaction performance since it's a one-time cost.
