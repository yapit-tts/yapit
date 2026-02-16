---
status: done
started: 2026-01-28
completed: 2026-01-28
---

# Task: iOS Mobile Sidebar UX Fixes

## Intent

Fix three iOS-specific issues with the mobile sidebar/outliner experience:
1. Edge trigger buttons can't be clicked (iOS reserves edge zones for system gestures)
2. Swipe gestures conflict with browser back/forward navigation
3. Document content drifts horizontally (known WebKit bug with overflow:hidden)

## Approach

### 1. Fix horizontal scroll (CSS)
Add iOS-specific CSS properties that the previous Android fix didn't need:
- `overscroll-behavior-x: none` — prevents rubber-band bouncing
- `touch-action: pan-y` — explicitly tells iOS to only allow vertical scrolling

### 2. Move sidebar/outliner buttons to playbar (mobile only)
Instead of floating edge buttons that conflict with iOS gestures:
- Add toggle buttons flanking the playbar (left = sidebar, right = outliner)
- More discoverable, always visible, in "safe zone" away from edges
- Icons: `PanelLeft` for sidebar, `List` for outliner

### 3. Remove floating edge buttons on mobile
- `sidebarEdgeTrigger.tsx` and `outlinerEdgeTrigger.tsx` return `null` on mobile
- Keep swipe gesture code — it works as secondary/power-user gesture
- Desktop behavior unchanged

## Assumptions

- The playbar has room for two small icon buttons on mobile
- Swipe gestures can remain as secondary interaction (buttons are primary)
- CSS fix will work across iOS versions (overscroll-behavior has good support)

## Sources

**Knowledge files:**
- [[frontend]] — Component hierarchy, mobile patterns

**External docs:**
- Reference: [WebKit bug #153852](https://bugs.webkit.org/show_bug.cgi?id=153852) — overflow:hidden scrollable on iOS
- Reference: [iOS edge gesture lag](https://blog.kulman.sk/why-ios-gestures-lag-at-the-screen-edges/) — why buttons at edges don't work

**Key code files:**
- MUST READ: `frontend/src/components/soundControl.tsx` — playbar component, add buttons here
- MUST READ: `frontend/src/components/sidebarEdgeTrigger.tsx` — remove mobile button
- MUST READ: `frontend/src/components/outlinerEdgeTrigger.tsx` — remove mobile button
- `frontend/src/index.css` — add overscroll-behavior CSS
- `frontend/src/layouts/SidebarLayout.tsx` — may need to pass toggle callbacks

## Done When

- [x] Horizontal scrolling fixed on iOS — added `overscroll-behavior-x: none` to html/body
- [x] Sidebar/outliner toggle buttons appear in playbar on mobile — `PanelLeft` and `List` icons aligned with time display
- [x] Floating edge buttons removed on mobile — edge triggers return `null` on mobile
- [x] Swipe gestures still work (as secondary interaction) — useEffect hooks run before early return
- [x] Desktop behavior unchanged — all changes conditional on `isMobile`
- [x] Fixed desktop horizontal scrollbar — negative margin trick only applies for "full" content width
- [x] Fixed tooltip auto-show on outliner open — replaced Radix Tooltip with native `title` attribute
- [x] Fixed filtered playback elapsed time — `filteredElapsedMs` calculated from visible blocks only
- [x] Tested on iOS Safari (user verification)
