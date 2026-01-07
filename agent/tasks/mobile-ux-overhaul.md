---
status: active
started: 2026-01-06
completed: 2026-01-06
---

# Task: Mobile UX & Design Overhaul

## Intent

Comprehensive fix for mobile responsiveness issues and design inconsistencies. Incorporates the sidebar edge trigger redesign from [[sidebar-edge-trigger]].

**User's observations (from screenshots):**

1. **No action buttons when no title** — Documents without titles (like plain text input) don't show copy/download/export buttons. Inconsistent UX.

2. **Sidebar trigger overlaps title** — On mobile, the fixed `SidebarTrigger` button crowds into the title area.

3. **Horizontal scroll on mobile** — Page can be scrolled horizontally (no scrollbar visible but scroll exists). Bad UX.

4. **Content cut off on left** — Title/content clips at left edge even with sidebar collapsed.

5. **Playback bar detaches** — When switching desktop/mobile views or zooming, the playback controls float instead of staying sticky at bottom.

**Desired outcome:**
- Clean, consistent mobile layout
- Action buttons always available (even without title)
- No horizontal scroll
- Proper spacing that accounts for sidebar trigger
- Eventually: edge-triggered sidebar (see [[sidebar-edge-trigger]])

## Analysis

### Root Causes

**1. Action buttons tied to title existence**

In `structuredDocument.tsx` lines 658-700 and 706-745, the action buttons are only rendered inside the title header `<div>`. When `!title`, there's no header at all → no buttons.

**Fix:** Create a separate header component that always renders action buttons. When title exists, show title + buttons. When no title, show just buttons (perhaps right-aligned or in a minimal toolbar).

**2. Sidebar trigger positioning**

In `SidebarLayout.tsx` line 9:
```tsx
<SidebarTrigger className="fixed backdrop-blur-lg" />
```

The trigger is `fixed` positioned but has no explicit `top`/`left` coordinates — it defaults to `top: 0, left: 0`. The document content uses `m-[10%]` margins which don't account for this fixed element.

**Fix options:**
- Give document content a `pl-[50px]` or similar left padding on mobile to clear the trigger
- Or: Move trigger inside the header area so it's part of the flow (not fixed)
- Or: Implement edge trigger (hover reveal) as in [[sidebar-edge-trigger]]

**3. Horizontal scroll**

Likely caused by:
- Content with `m-[10%]` + elements overflowing
- Fixed elements with implicit positioning
- Something setting `width > 100vw`

**Fix:** Add `overflow-x: hidden` to body/main container. Audit content margins on mobile breakpoints.

**4. Content clipping**

The `m-[10%]` margin doesn't leave enough room on narrow screens when combined with the sidebar trigger in the corner.

**Fix:** Use responsive margins: `mx-4 sm:mx-[8%] md:mx-[10%]` or similar.

## Relevant Files

- `frontend/src/components/structuredDocument.tsx` — Document view with title + action buttons
- `frontend/src/layouts/SidebarLayout.tsx` — Sidebar trigger placement
- `frontend/src/components/ui/sidebar.tsx` — SidebarTrigger component
- `frontend/src/pages/PlaybackPage.tsx` — Overall page structure
- `frontend/src/index.css` — Global styles
- `frontend/src/components/soundControl.tsx` — Playback bar (need to check sticky behavior)

## Sources

- **MUST READ**: [[sidebar-edge-trigger]] — Related task for sidebar UX redesign
- Screenshots: User's mobile screenshots showing overlap, cutoff, horizontal scroll

## Implementation Plan

### Phase 1: Fix Critical Mobile Bugs

1. **Always show action buttons** — Refactor `StructuredDocumentView` to have a consistent header/toolbar regardless of title
2. **Fix horizontal scroll** — Add `overflow-x-hidden` at appropriate level, audit margins
3. **Fix left cutoff** — Use responsive margins that account for sidebar trigger space

### Phase 2: Header/Toolbar Redesign

1. **Separate header component** — Extract title + action buttons into a reusable header
2. **Mobile-specific layout** — Stack buttons below title on mobile, beside on desktop
3. **Position sidebar trigger** — Integrate with header or implement edge trigger

### Phase 3: Sidebar Edge Trigger (Optional Enhancement)

Per [[sidebar-edge-trigger]]:
- Replace visible trigger button with hover-reveal edge zone
- Implement swipe gesture for mobile

## Follow-up Items

- **Block info display cleanup** — "Block X of Y" on desktop gets cramped when voice names are long. Consider: integrate into progress bar area, show on hover, or move to a more subtle location. See `soundControl.tsx` lines 662-664.
- **Voice picker improvements** — Separate task, more involved than visual fixes.

## Implementation Summary

All issues resolved:

1. **Action buttons always visible** — Refactored `structuredDocument.tsx` to extract an `ActionButtons` component that always renders. When no title, buttons are right-aligned; when title exists, they're beside the title.

2. **Fixed horizontal scroll** — Added `overflow-x-hidden` to main container in `SidebarLayout.tsx`.

3. **Fixed content spacing** — Changed from `m-[10%]` to responsive `px-4 sm:px-[8%] md:px-[10%] pt-4 sm:pt-[4%]` in `structuredDocument.tsx`.

4. **Fixed tooltip annoyance** — Added `hidden={isMobile}` to the "Click to view plans" tooltip in `documentSidebar.tsx` so it no longer auto-shows when sidebar opens on mobile.

5. **Implemented sidebar edge trigger** — Created new `SidebarEdgeTrigger` component:
   - **Desktop**: Invisible 40px edge zone on left. Hover reveals a chevron button (100ms delay prevents accidental triggers). Click toggles sidebar.
   - **Mobile**: Swipe-from-left gesture (50px threshold) opens sidebar. Subtle visual hint strip on left edge.

### Files Changed

- `frontend/src/components/structuredDocument.tsx` — Action buttons + responsive margins
- `frontend/src/layouts/SidebarLayout.tsx` — Edge trigger + overflow fix
- `frontend/src/components/sidebarEdgeTrigger.tsx` — New component (hover-reveal + swipe)
- `frontend/src/components/documentSidebar.tsx` — Hide tooltip on mobile

## Gotchas

- DevTools MCP can't easily test hover-reveal elements (synthetic events don't trigger React state). Manual testing needed for hover behavior.
- iOS Safari swipe-from-left might conflict with browser back gesture — needs real device testing.

## Considered & Rejected

- **Keeping the old button but repositioning** — User wanted edge trigger for cleaner UI.
- **Auto-open on hover** — Decided against because it could be annoying. Click/tap required to actually open.

## Handoff Notes (2026-01-06)

### What's Done & Committed
- ✅ Action buttons always visible (even without title) — `structuredDocument.tsx`
- ✅ Responsive margins (`px-4 sm:px-[8%] md:px-[10%]`) — `structuredDocument.tsx`
- ✅ `overflow-x-hidden` on main container — `SidebarLayout.tsx`
- ✅ Tooltip hidden on mobile — `documentSidebar.tsx`
- ✅ Edge-hover sidebar trigger — `sidebarEdgeTrigger.tsx` + `SidebarLayout.tsx`

### Edge Trigger Implementation (2026-01-06)

**Root cause of original issue:** The previous implementation didn't have `group-hover` at all — it was just a visible button. The code was simplified/removed when it "didn't work", but the actual `group-hover` pattern was never properly implemented.

**Fix:** Reimplemented `SidebarEdgeTrigger` with proper Tailwind `group` / `group-hover:` pattern:
- Desktop: Invisible 40px edge zone at left viewport edge. Button has `opacity-0 group-hover:opacity-100` — appears on hover over the edge zone.
- Mobile: Always-visible button at `fixed left-2 top-2` + swipe gesture (unchanged from before).
- Updated `SidebarLayout.tsx` to use `SidebarEdgeTrigger` instead of the old `SidebarTrigger`.

**Verified working via DevTools MCP:**
- Hover on edge zone → button appears
- Click elsewhere → button hides
- Mobile → button always visible

### Remaining Consideration
- When sidebar is open on desktop, the edge zone is at viewport left (under the sidebar). This is fine since the sidebar has its own close button. The edge trigger is primarily useful when sidebar is collapsed.

### Files Changed
- `frontend/src/components/sidebarEdgeTrigger.tsx` — Proper group-hover implementation (untracked)
- `frontend/src/layouts/SidebarLayout.tsx` — Uses SidebarEdgeTrigger instead of SidebarTrigger

---

## New Issues (2026-01-07)

Three new mobile UX issues reported:

### Issue 1: Title Edit vs Link Click Conflict

**Problem:** For documents with a source URL, clicking whitespace to the right of the title text still opens the link instead of entering edit mode.

**Root cause:** In `structuredDocument.tsx:750-776`, the h1 element (with onClick for opening URL) is a block-level element in a `flex flex-col` container on mobile, so it takes full width. Any click on that row triggers the h1's onClick (which opens URL and stops propagation), preventing the parent div's onClick (which triggers editing) from firing.

**Files:** `structuredDocument.tsx:750-776`

### Issue 2: Horizontal Scroll Still Happening

**Problem:** On certain documents, horizontal scrolling is possible even though content appears to fit. Can scroll right until nothing is visible.

**Analysis:** `SidebarLayout.tsx` already has `overflow-x-hidden` on main container (added in previous fix). This suggests something else is causing the issue:
- Possibly an element outside the main container
- Or body/html level overflow
- Or specific content in certain documents (tables, code blocks, long URLs) causing issues

**Files:** Need to investigate further — could be `index.css`, `App.tsx`, or specific document content

### Issue 3: No Document Title Validation

**Problem:** No restrictions on document title length or content.

**Current state:**
- `domain_models.py:80`: `title: str | None = Field(default=None)` — no max_length
- `documents.py:411-412`: `DocumentUpdateRequest` has `title: str | None = None` — no validation
- Frontend: No `maxLength` on input field

**Risks:**
- Very long titles could break UI layouts
- Database storage waste
- Performance impact on queries

**Recommendation:** Add validation at all layers (defense in depth):
1. Database: `Field(max_length=500)` on Document.title
2. API: `Field(max_length=500)` on DocumentUpdateRequest.title
3. Frontend: `maxLength={500}` on title input
