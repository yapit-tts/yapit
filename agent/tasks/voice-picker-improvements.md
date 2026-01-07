---
status: active
started: 2026-01-03
---

# Task: Voice Picker Improvements

## Issues

1. **Default to cloud Kokoro for subscribers** — if user has active plan, default to Cloud; if no plan, grey out Cloud with tooltip

2. **Inworld tab permissions** — entire Inworld tab should be disabled/greyed for free users (currently accessible)

3. **Info button for "Runs on" toggle** — explain Local (browser, slower on some devices) vs Cloud (server, faster, requires subscription). Similar to Inworld's Quality tooltip.

3. **Star button hitbox too small** — hard to tap on mobile

4. **Filter Kokoro local to English only** — browser WASM model only supports English, don't show other languages when Local selected

5. **Slow local inference hint** (nice-to-have) — if browser TTS takes too long, show hint with "Start trial" or "Export as MP3" options

## Files

- `frontend/src/components/voicePicker.tsx`
- `frontend/src/hooks/useSubscription.tsx` (new)
- `frontend/src/App.tsx` (added SubscriptionProvider)

## Implementation Notes (2026-01-07)

**Completed:**
1. Created `useSubscription` hook/context for shared subscription state
2. Added info button to Local/Cloud toggle with tooltip explaining the difference
3. Fixed star button hitbox with `p-2 -m-1 touch-manipulation` (32px touch target)
4. Fixed star alignment — now vertically centered in rows
5. Added English-only filter for Local mode (filters both voice groups and starred voices)
6. Auto-switches to `af_heart` when switching to Local if current voice isn't English
7. Subscribers default to Cloud on mount
8. Cloud button shows lock icon + tooltip for free users
9. Inworld tab shows lock icon + tooltip for free users

**Additional changes (fixing bugs found in testing):**
- Fixed gating logic: Cloud uses `canUseCloudKokoro` (Basic, Plus, Max), Inworld uses `canUseInworld` (Plus, Max only)
- Updated tooltip text: removed redundant "Requires subscription" from info tooltip, Inworld tooltip now says "Requires Plus or Max subscription"

**Not implemented:**
- Issue 5 (slow local inference hint) — requires instrumenting browser TTS timing, deferred

## Performance Optimizations (2026-01-07)

Applied to reduce sluggishness when toggling Local/Cloud:

1. **CSS hiding for non-English groups** — All Collapsible sections stay in DOM, non-English hidden via CSS class in Local mode. Prevents unmount/remount flicker.

2. **useMemo for voice groups** — `kokoroVoiceGroups`, `inworldVoiceGroups`, `pinnedKokoro`, `pinnedHiggs`, `pinnedInworld` wrapped in useMemo to prevent recalculation on every render.

3. **React.memo on VoiceRow** — Custom comparison function ignores `onSelect`/`onPinToggle` props (recreated every render) to prevent unnecessary re-renders of ~50+ list items.

## Known Issues / Tech Debt

**Document headers briefly show dotted underline when toggling Local/Cloud:**

When switching Local↔Cloud, document content headers (like "Statistics", "Meta-Science") briefly flash with a dotted underline, then return to normal.

**Root cause investigation:**
- Headers are wrapped in anchor tags (`<a href="#...">`) by backend for permalink functionality
- CSS rule `.structured-content a[href^="#"]:not(.dead-link)` applies dotted underline to internal links
- The `.dead-link` class is added dynamically via useEffect to mark broken anchor links
- Hypothesis: On some re-render, the class is briefly removed causing the underline to flash

**What we tried that didn't work:**
- Adding CSS rule `h1 a, h2 a, ... { text-decoration: none }` — flicker persisted
- The mystery: StructuredDocumentView is wrapped in `memo()` and its props don't change when voice changes, yet something still triggers the visual glitch

**Next steps if this becomes annoying:**
- Use React DevTools Profiler to confirm if StructuredDocumentView actually re-renders
- Check if Radix Popover does something that triggers browser style recalculation
- Consider moving the `<style>` tag outside the component to a global stylesheet
