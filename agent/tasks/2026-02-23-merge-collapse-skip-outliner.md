---
status: done
refs: []
---

# Merge section collapse and skip into a single toggle

## Intent

The outliner currently has two independent section states: **collapse** (hides content visually + from progress bar, but still plays audio) and **skip** (excludes from playback entirely, hides everything including heading). This distinction is confusing — collapsing a section while still hearing it is surprising, and the two controls (click +/- vs right-click → exclude) add complexity without clear benefit.

Merge into one toggle: collapsed = skipped. A collapsed section shows its heading (grayed, with expand chevron), is excluded from the progress bar, and is skipped during playback. Expanding re-includes it.

## Assumptions

- Nobody relies on "collapse but still play" behavior. The auto-expand-on-cursor-advance mitigated its weirdness but also made it feel like collapse already meant skip.
- The right-click "exclude from playback" context menu becomes redundant and should be removed.
- The heading of a collapsed/skipped section should remain visible (grayed, clickable to re-expand). The old "skip" behavior that hid headings entirely is not needed.

## Done When

- Single toggle (+/- or chevron) collapses a section: heading stays visible (grayed), content hidden, excluded from progress bar, skipped during playback.
- Clicking a collapsed heading (or its +/chevron) re-expands and re-includes in playback.
- Right-click context menu removed (or repurposed if there's a reason to keep it).
- `skippedSections` state eliminated — `expandedSections` is the single source of truth for visibility and playback.
- `filterVisibleBlocks`, `useFilteredPlayback`, and the playback engine all use only `expandedSections`.
- Auto-expand-on-cursor-advance logic still works (expands a collapsed section when playback reaches it — or does it? Decision: if collapsed = skipped, the engine skips it, so cursor never reaches it. The auto-expand logic can be removed.)

## Scope

Files involved:
- `frontend/src/pages/PlaybackPage.tsx` — remove `skippedSections` state, simplify handlers
- `frontend/src/components/documentOutliner.tsx` — remove skip popover/context menu, simplify toggle
- `frontend/src/lib/filterVisibleBlocks.ts` — remove `skippedSections` param, use only `expandedSections`
- `frontend/src/hooks/useFilteredPlayback.ts` — same
- `frontend/src/hooks/usePlaybackEngine.ts` — pass `expandedSections` as skip set (inverted: not-expanded = skipped)
- `frontend/src/lib/playbackEngine.ts` — `setSections` takes the set of skipped section IDs (derived from non-expanded)
- localStorage schema for outliner state: currently `{ expanded: [], skipped: [] }` → simplify to `{ expanded: [] }`

## Considered & Rejected

**Keep both toggles but make them more discoverable.** Rejected because the "collapse but still play" use case has no real-world scenario. Two toggles for one concept adds confusion without value.
