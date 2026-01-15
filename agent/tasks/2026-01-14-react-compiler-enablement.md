---
status: done
started: 2026-01-14
completed: 2026-01-15
commit: 90d184f
---

# Task: Enable React Compiler

## Intent

Enable React Compiler (`babel-plugin-react-compiler`) to get automatic memoization. The codebase already has extensive manual memoization (`useMemo`, `useCallback`, `memo()`), but the compiler can catch cases humans miss and remove the maintenance burden for new code.

## Context

Prompted by [this tweet](tweet-screenshot) showing how React Compiler auto-memoizes expensive derived state that would otherwise re-run on every render. Without the compiler, code like:

```tsx
const nextFivePrimes = getNextFivePrimes(randomNum);
```

...re-runs on every state change (including unrelated input changes), causing lag. Traditionally requires manual `useMemo`. Compiler handles it automatically.

## Current State Analysis

### Existing Memoization (Safe)

Heavy manual memoization already in place:

| Pattern | Count | Files |
|---------|-------|-------|
| `useCallback` | ~50+ | PlaybackPage, soundControl, useTTSWebSocket, etc. |
| `useMemo` | ~20+ | structuredDocument, voicePicker, soundControl, etc. |
| `memo()` | 3 | `StructuredDocumentView`, `VoiceRow`, `SoundControl` |

**Good news:** React Compiler preserves existing manual memoization. From the docs: "The compiler will only compile components and hooks if its inference matches or exceeds the existing manual memoization." Existing `useMemo`/`useCallback`/`memo()` won't cause issues.

### Large Components (Highest Impact)

| File | Lines | Notes |
|------|-------|-------|
| `PlaybackPage.tsx` | 1465 | Main playback logic, heavy state |
| `structuredDocument.tsx` | 997 | Already uses `memo()` |
| `soundControl.tsx` | 777 | Already uses `memo()` |
| `voicePicker.tsx` | 599 | Uses `memo()` on VoiceRow |

### Known Violations (Must Fix First)

**PlaybackPage.tsx:130 - Ref mutation during render:**
```tsx
currentBlockRef.current = currentBlock; // Sync ref with state for use in callbacks
```

This is explicitly flagged in React docs as a violation:
> "Don't write a ref during rendering" - react.dev/reference/react/useRef

This pattern is used to make current state available in async callbacks without stale closures. The fix: move to a `useEffect`:

```tsx
// INSTEAD OF:
currentBlockRef.current = currentBlock;

// USE:
useEffect(() => {
  currentBlockRef.current = currentBlock;
}, [currentBlock]);
```

There may be other subtle violations. The ESLint plugin can find them.

## Risk Assessment

### Low Risk
- **Existing memoization preserved** — compiler respects manual `useMemo`/`useCallback`/`memo()`
- **Escape hatch exists** — `"use no memo"` directive can opt out specific components
- **Build-time only** — no runtime changes if compiler decides not to optimize
- **React 19 compatible** — we're on React 19.0.0, compiler is designed for it

### Medium Risk
- **Ref mutations during render** — at least one known violation (PlaybackPage:130), possibly more
- **Side effects during render** — any logging/analytics during render could behave differently if cached
- **Build time increase** — compiler adds analysis step (typically minor)

### What Could Go Wrong
1. **Ref sync bugs** — if ref mutation during render is removed without proper useEffect, async callbacks could see stale values
2. **Unexpected caching** — any impure render logic gets cached, causing subtle bugs
3. **Performance regression** — unlikely, but possible if compiler makes wrong inference

## Verification Plan

### Phase 1: Pre-Flight Check (Before Enabling)

1. **Install ESLint plugin** (without compiler)
   ```bash
   npm install -D eslint-plugin-react-compiler@beta
   ```

2. **Add to eslint config** and run:
   ```js
   plugins: {
     'react-compiler': reactCompiler,
   },
   rules: {
     'react-compiler/react-compiler': 'error',
   }
   ```

3. **Fix all violations** — especially the ref mutation at PlaybackPage:130

### Phase 2: Enable Compiler

1. **Install compiler**
   ```bash
   npm install -D babel-plugin-react-compiler
   ```

2. **Update vite.config.ts**
   ```ts
   react({
     babel: {
       plugins: [["babel-plugin-react-compiler"]],
     },
   })
   ```

3. **Build and verify** — `npm run build` should succeed

### Phase 3: Functional Verification

Manual testing checklist:

- [ ] App loads without React errors/warnings in console
- [ ] Document playback works (play/pause/seek)
- [ ] Voice switching works
- [ ] Progress bar hover/drag works smoothly
- [ ] Document sidebar navigation works
- [ ] Settings persist correctly
- [ ] No visible regressions

### Phase 4: Performance Spot-Check

Use React DevTools Profiler on PlaybackPage with a large document:
- Typing in input shouldn't re-render unrelated components
- Progress bar hover shouldn't trigger expensive re-renders

## Considered & Rejected

### Incremental Rollout via `compilationMode: 'annotation'`
Could use `compilationMode: 'annotation'` to only compile components marked with `'use memo'` directive. Rejected because:
- Extra maintenance burden (adding directives everywhere)
- Codebase is small enough for full adoption
- ESLint plugin catches violations before enabling

## Sources

**External docs:**
- MUST READ: [React Compiler Installation](https://react.dev/learn/react-compiler/installation)
- Reference: [useRef - Don't read/write during render](https://react.dev/reference/react/useRef)
- Reference: [ESLint plugin lints](https://react.dev/reference/eslint-plugin-react-hooks/lints)
- Reference: [React Compiler Beta Release](https://react.dev/blog/2024/10/21/react-compiler-beta-release)

## Done When

- [ ] ESLint plugin installed and passing (no violations)
- [ ] React Compiler enabled in vite.config.ts
- [ ] Build succeeds
- [ ] Functional verification checklist passes
- [ ] No React warnings/errors in console
