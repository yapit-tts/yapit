# Frontend CSS Patterns

Gotchas and patterns discovered while building the UI.

## Visual Effects Without Layout Shift

**Problem**: Adding `padding` to highlighted text (e.g., active block highlighting) causes text reflow - words wrap differently, content shifts.

**Solution**: Use `box-shadow` to extend visual highlighting without affecting layout:

```css
/* Block-level: extend background to the left without padding */
.audio-block-active {
  background: oklch(0.55 0.1 133.7 / 0.15);
  box-shadow: -0.25rem 0 0 oklch(0.55 0.1 133.7 / 0.15);
}

/* Inline spans: extend both sides */
span.audio-block-active {
  background: oklch(0.55 0.1 133.7 / 0.15);
  box-shadow: 0.15rem 0 0 oklch(0.55 0.1 133.7 / 0.15),
              -0.15rem 0 0 oklch(0.55 0.1 133.7 / 0.15);
  box-decoration-break: clone; /* For multi-line spans */
}
```

The `box-shadow` creates visual "breathing room" without affecting the box model.

## OKLCH Neutral Gray Appears Blue

**Problem**: Pure OKLCH gray (`oklch(0.92 0 0)` - zero chroma) can appear slightly blue/purple on some displays.

**Solution**: Add a tiny warm tint to counteract:

```css
/* Instead of pure gray: */
--muted-gray: oklch(0.92 0 0);       /* Can appear bluish */

/* Use: */
--muted-gray: oklch(0.94 0.015 95);  /* Tiny warm tint, appears neutral */
```

Hue 90-95 (yellow range) with very low chroma (0.01-0.02) reads as neutral gray to human eyes.

## Visual State vs Buffer State

**Problem**: When displaying cache state in a progress bar, using the actual audio buffer (`audioBuffersRef`) as the source of truth causes visual bugs - old blocks appear "uncached" after eviction even though backend cache still has them.

**Solution**: Keep two separate tracking mechanisms:

```tsx
// Actual buffer - evicts old blocks for memory management
const audioBuffersRef = useRef<Map<number, AudioBufferData>>(new Map());

// Visual tracking - never evicts, shows "ever cached this session"
const cachedBlocksRef = useRef<Set<number>>(new Set());

// When caching audio:
audioBuffersRef.current.set(blockId, data);
cachedBlocksRef.current.add(blockId);  // Never removed

// For visual state derivation:
if (cachedBlocksRef.current.has(block.id)) return 'cached';  // Use this
// NOT: if (audioBuffersRef.current.has(block.id)) return 'cached';
```

Clear `cachedBlocksRef` when voice changes (audio needs re-synthesis) but not on buffer eviction.

## macOS Overlay Scrollbar Layout Shift

**Problem**: On macOS (with overlay scrollbars), Radix UI dropdowns/dialogs add `overflow: hidden` to body for scroll locking. This makes the overlay scrollbar disappear, causing content to shift slightly. On close, scrollbar reappears → visible "flicker."

Not reproducible on Linux (scrollbars always visible) or Windows (depends on settings).

**Solution**: Reserve scrollbar space permanently:

```css
html {
  scrollbar-gutter: stable;
}
```

This reserves space for the scrollbar even when it's hidden, preventing layout shift. Works across all platforms without visible impact where scrollbars are always shown.

## Padding + Negative Margin for Background Extension

**Problem**: `box-shadow` gets clipped by `overflow: auto` on parent containers. Need another way to extend background without shifting text position.

**Solution**: Apply both padding AND negative margin. They cancel out for text position, but padding creates space for background to extend into:

```css
.element {
  padding-left: 0.625rem;
  padding-right: 0.625rem;
  margin-left: -0.625rem;
  margin-right: -0.625rem;
  border-radius: 0.5rem;
}
```

When background is applied (e.g., on highlight), it fills the padded area. Text stays in original position because padding and negative margin cancel out.

**Use case**: Block-level element highlighting where parent has `overflow-y: auto`.

## Callback Ref Pattern for Stable Hooks

**Problem**: Callbacks passed to custom hooks become stale when captured in closures (e.g., setTimeout, setInterval). The callback at time of capture may be outdated when the timer fires.

**Solution**: Store callback in a ref that's always kept up to date:

```tsx
function useRepeatOnHold(callback: () => void) {
  const callbackRef = useRef(callback);

  // Keep ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const startRepeating = useCallback(() => {
    const repeat = () => {
      callbackRef.current(); // Always uses latest callback
      setTimeout(repeat, 100);
    };
    setTimeout(repeat, 400);
  }, []); // No callback in deps - ref handles it

  // ...
}
```

This prevents stale closure bugs where the callback references old state/props.
