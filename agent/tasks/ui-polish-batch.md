---
status: done
type: implementation
---

# UI Polish Batch - Colors, Progress Bar, Highlights

**Knowledge extracted:** [[frontend-css-patterns]]

Batch of UI improvements based on user feedback. Main themes: reduce green overload, make progress bar actually show progress, improve text highlighting aesthetics.

## Completed

All 5 main issues + additional polish:

1. **Progress bar colors** ✅ - New color scheme: pending=warm brown, cached=light green, current=solid green
2. **Cache state visual bug** ✅ - Added `cachedBlocksRef` Set to track "ever cached this session"
3. **Code block background** ✅ - Changed to `bg-muted-warm`
4. **Text highlight styling** ✅ - Added box-shadow for breathing room, border-radius for rounded corners
5. **Toggle switch off-state** ✅ - Changed to `bg-muted-warm`
6. **Display math background** ✅ - Changed to neutral gray (`bg-muted-gray`)
7. **Table headers** ✅ - Changed to distinct brown (`bg-muted-table`)
8. **Progress bar hover** ✅ - Changed from yellow to green (matches current playing)
9. **Synthesizing indicator** ✅ - Removed pulse animation, static muted yellow

10. **Sidebar scroll flicker** ✅ - Added `scrollbar-gutter: stable` to prevent macOS overlay scrollbar layout shift (needs testing on Mac)

Trackpad double-click issue not addressed - likely hardware/browser-specific.

## Constraints / Design Decisions

**Color scheme:**
- Green reserved for: current playing block, primary buttons, important highlights
- Brown/tan for: backgrounds, uncached/pending states, code blocks, inactive toggles
- Yellow for: synthesizing, hover/seek preview

**Brown/tan color (new `--muted-warm`):**
- OKLCH hue ~70 (brown) vs current ~115 (green)
- Same lightness/saturation as current muted: oklch(0.86 0.05 70)
- Defined as CSS variable in index.css for consistency

## Issues

### 1. Progress Bar Colors - Too Much Green, Current Block Not Obvious

**Problem:** The progress bar has too many shades of green - pending (muted green), cached (green/60), current playing (solid green). They're too similar. The "where are we now" (current playing block) should be the obvious focal point, but it gets lost among all the green.

**Current colors:**
- Pending/uncached: muted green (`bg-muted/50` which is greenish)
- Cached: `bg-primary/60` (green at 60% opacity)
- Current playing: `bg-primary` (solid green)
- Synthesizing: yellow pulse (this is fine)

**Proposed colors:**
- Pending/uncached: light brown/tan/beige (warm muted color, like the muted green but brown)
- Cached: light green (what's currently the "muted green")
- Current playing: darker/primary green - should be OBVIOUS, the focal point
- Synthesizing: yellow pulse (unchanged)

**Goal:** At first glance, it should be immediately clear where playback is. Green is reserved for "important/active" - the current position should pop.

**Files:** `frontend/src/components/soundControl.tsx` (BlockyProgressBar and SmoothProgressBar color logic)

### 2. Cache State Visual Bug - Frontend vs Backend Cache Confusion

**Problem:** When you jump forward in a document, previous blocks turn visually gray/uncached. But they're still cached in the backend and play instantly without re-synthesis. The visual is misleading.

**Root cause:** The progress bar displays frontend audio buffer state (what's in `audioBuffersRef`), which gets evicted after a few blocks. But backend cache (Redis) persists much longer.

**Current behavior:**
- Block plays → cached in frontend buffer + backend
- User jumps forward → frontend evicts old blocks from buffer
- Old blocks appear "uncached" even though backend still has them
- User goes back → plays instantly (backend cache hit), but visual was wrong

**Desired behavior:** Visual state should reflect "will this play instantly?" which means backend cache state, not frontend buffer state.

**Possible approaches:**
1. Track "ever cached this session" separately from "in frontend buffer" - once cached, stays visually cached
2. Accept that state resets, but update correctly when block is played (if backend returns cached audio, mark as cached)
3. Query backend cache state (probably overkill)

**Recommendation:** Option 1 seems cleanest - add a `Set<blockId>` that tracks "blocks we've received audio for this session". This is separate from `audioBuffersRef` which is the actual buffer. Progress bar uses this set for visual state.

**Files:** `frontend/src/pages/PlaybackPage.tsx` (state management), `frontend/src/components/soundControl.tsx` (display)

### 3. Code Blocks Should Use Brown Background, Not Green

**Problem:** Code blocks (triple backtick) have a greenish background, contributing to "everything is green" problem. Green should be reserved for primary/highlighted/important things.

**Proposed:** Use a light brown/tan/beige for code block backgrounds. Should be subtle/muted, not dark.

**Files:** `frontend/src/components/structuredDocument.tsx` (CodeBlockView component, look for `bg-muted`)

### 4. Text Highlight Styling - Needs Padding and Rounding

**Problem:** The yellow hover highlight and green active highlight on document blocks start exactly at the first character - feels "claustrophobic". No breathing room.

**Proposed:**
- Add small left padding so highlight extends slightly before text starts
- Make corners more rounded
- More noticeable on regular paragraph blocks, less important for blockquotes

**Files:** `frontend/src/components/structuredDocument.tsx` (CSS for `.audio-block-active` and `.audio-block-hovered`)

### 5. Toggle Switch Off-State Color

**Problem:** Toggle switches (e.g., in settings) have white background when off. Should use light brown instead to match the warm aesthetic.

**Files:** Likely `frontend/src/components/ui/switch.tsx` or wherever shadcn switch is styled

### 6. Minor: Sidebar Menu Scroll Flicker

**Problem:** Clicking the three-dots menu on sidebar document items causes scrollbar to appear/disappear (layout shift). Same with settings gear icon.

**Suspicion:** Might be related to scroll locking when dropdown/dialog opens.

**Files:** Need to investigate - likely in sidebar component or dropdown styling

### 7. Minor: Trackpad Double-Click on Three Dots Menu

**Problem:** Tapping the three-dots menu with trackpad seems to double-click, immediately opening the edit dialog instead of just showing the dropdown.

**Note:** Might be a user/hardware issue, but worth investigating.

---

## Implementation Priority

1. Progress bar colors (high impact, relatively contained change)
2. Cache state visual bug (confusing UX, moderate complexity)
3. Code block colors (easy win)
4. Text highlight styling (easy win)
5. Toggle switch color (easy win)
6. Scroll flicker (minor, needs investigation)
7. Trackpad double-click (minor, might not be fixable)

## Color Reference

Need to establish the "light brown/tan/beige" color. Should be:
- Warm, fits Ghibli aesthetic
- Muted, not attention-grabbing
- Similar saturation/lightness to the current muted green, just shifted to brown hue
- Check existing theme colors before adding new ones

Look at: `frontend/src/index.css` for existing theme variables

## Notes

- Green should be reserved for: current playing block, primary buttons, important highlights
- Brown/tan for: backgrounds, uncached/pending states, code blocks, inactive toggles
- Yellow for: synthesizing (static, no pulse)
- Hover/seek preview now uses same green as current (lighter opacity)

---

## Work Log

### 2025-12-30 - Implementation Complete

**Completed all 5 main issues:**
1. Progress bar colors - added `--muted-warm`, `--muted-gray`, `--muted-table` CSS variables
2. Cache state visual bug - added `cachedBlocksRef` Set separate from buffer
3. Code block background - changed to `bg-muted-warm`
4. Text highlight styling - used `box-shadow` for breathing room (padding caused text reflow)
5. Toggle switch - changed to `bg-muted-warm`

**Additional fixes during session:**
- Display math background - `--muted-gray` (neutral gray with tiny warm tint to avoid blue cast)
- Table headers - `--muted-table` (distinct brown shade)
- Progress bar hover - changed from yellow to green (same as current playing)
- Synthesizing indicator - removed pulse animation, made static muted yellow

**Key learnings extracted to [[frontend-css-patterns]]:**
- `box-shadow` for visual effects without layout shift
- OKLCH gray needs warm tint to appear neutral
- Visual state tracking separate from buffer state

**Files modified:**
- `frontend/src/index.css` - Added 3 new CSS variables
- `frontend/src/components/soundControl.tsx` - Progress bar colors, removed pulse
- `frontend/src/components/structuredDocument.tsx` - Code/math/table backgrounds, highlight styling
- `frontend/src/components/ui/switch.tsx` - Toggle off-state color
- `frontend/src/pages/PlaybackPage.tsx` - Added `cachedBlocksRef` for visual state tracking

### 2025-12-30 - Highlight Refinements & Skip Button UX

**Continued polish on highlights and added playback UX improvements:**

1. **Unified muted-brown color** - Renamed `--muted-gray` to `--muted-brown`, unified code blocks, math blocks, and table headers to use same color (oklch 0.9036 0.029 91.66)

2. **Fixed double-highlight issue** - Inner elements (HeadingBlockView, ParagraphBlockView, ListBlockView) were also getting highlight styles, causing layered highlighting. Moved clickableClass to wrapper divs only.

3. **Text position preservation** - Used `padding + negative margin` technique to keep text in original position while allowing background to extend on highlight. Padding creates space for highlight, negative margin cancels out the position shift.

4. **Span padding minimized** - Reduced inline span padding to 1px (0.0625rem) to preserve paragraph flow. Increased border-radius to 4px for visible rounding.

5. **Hold-to-repeat for skip buttons** - Fixed stale callback issue using `callbackRef` pattern. Added gentler acceleration (0.92 factor, 75ms min interval).

6. **Scroll behavior improvements:**
   - Skip buttons now scroll to target block (if live scroll enabled)
   - Playback start immediately scrolls to current block
   - Added `scrollToBlock` helper function

**Key CSS pattern (padding + negative margin):**
```css
.element {
  padding-left: 10px;
  padding-right: 10px;
  margin-left: -10px;
  margin-right: -10px;
}
```
Text stays in place, but background extends into padded area when applied.

**Callback ref pattern for stable callbacks in hooks:**
```tsx
const callbackRef = useRef(callback);
useEffect(() => { callbackRef.current = callback; }, [callback]);
// Use callbackRef.current in timeouts/intervals
```
Prevents stale closures when callback changes between timer fires.
