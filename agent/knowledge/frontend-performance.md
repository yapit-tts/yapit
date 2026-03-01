# Frontend Performance

Optimization patterns and measurement techniques for large documents (10k+ blocks). See [[frontend-performance-tracking]] for the full decision trail, measurements, and methodology.

## Where Time Goes (j/k navigation on 12k blocks / 48k DOM)

| Layer | Cost |
|---|---|
| React render (overlay + all children) | **0.1ms** |
| classList highlight effect | **3ms** |
| scrollIntoView | **~25ms** |
| Browser style recalc + layout + paint | **~50ms** |
| **Total** | **~75ms median** (spikes to ~300ms from GC) |

JS is fully optimized (~3ms total). The remaining cost is the browser processing 48k DOM nodes. The only fix is rendering fewer nodes (virtualization).

### What doesn't help

- CSS `contain: layout style paint` — <5ms on this tree
- CSS `content-visibility: auto` — makes things worse (visibility recalc on class toggle)
- Removing transitions — no effect (color-only, not geometry)
- React memo/hook optimizations — render is already 0.1ms
- `querySelectorAll` → Map — saves 2.4ms, adds sync complexity with section collapse

## Architecture

**Key pattern — snapshot subscriber isolation:** Only `PlaybackOverlay` subscribes to the engine's snapshot store via `useSyncExternalStore`. PlaybackPage is a static shell that never re-renders on cursor changes. Communication via ref bridges (`scrollToBlockRef`, `currentBlockRef`, `handleBackToReadingRef`).

**Key pattern — ref-based decoupling:** When a memo'd component receives a value only needed at interaction time (click, hover), pass a stable callback that reads from a ref instead. See `canCollapseSection` in `PlaybackPage.tsx`.

**Why SoundControl memo "works" despite being busted:** `progressBarValues` is a new object every overlay render → SoundControl's `React.memo` always re-renders. But the render is 0ms because all internal hooks return cached values and SmoothProgressBar's gradient useMemo holds (blockStates is reference-stable during j/k — engine caches via `blockStatesVersion`).

## Measurement

**Fixtures:** `scripts/seed_perf_fixtures.py` — titles: `[perf] {flat|sectioned|dense} {100|500|...|10000}b`.

**Total interaction cost** (JS + React + paint):
```js
() => new Promise(resolve => {
  const t0 = performance.now();
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true }));
  requestAnimationFrame(() => requestAnimationFrame(() =>
    resolve({ totalMs: Math.round((performance.now() - t0) * 10) / 10 })
  ));
})
```

**Component render timing** (add temporarily, remove after):
```tsx
// At start of function component body:
const __t0 = performance.now();
// Before return statement:
const __ms = Math.round((performance.now() - __t0) * 100) / 100;
(window as any).__component_ms = __ms;
```

**Isolation testing** — neuter specific operations to decompose cost:
```js
// Skip scrollIntoView to isolate its cost:
Element.prototype.scrollIntoView = function() {};
// Skip classList to isolate highlight cost:
DOMTokenList.prototype.add = function(...a) {
  if (a[0] === 'audio-block-active') return;
  return origAdd.apply(this, a);
};
```

**Pitfall: 2×rAF alone is misleading.** It mixes JS, React, and browser paint into one number. Always decompose with component timing + isolation tests before attributing cost. Previous agents reported "2.5ms JS / 360ms React reconciliation" — both wrong. The actual split was 3ms JS / 72ms browser.
