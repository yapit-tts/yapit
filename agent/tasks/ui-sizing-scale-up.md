---
status: done
started: 2026-01-01
completed: 2026-01-01
---

# Task: UI Sizing Scale-Up

The entire app trended too small at default zoom. Users needed to zoom to 130-150% in Firefox to get comfortable sizing.

## Intent

**User's mental model:** The app should be comfortable at 100% browser zoom for most users. Previously felt cramped — like something designed for very high-DPI displays viewed at a distance.

**Target:** Apple's 44px minimum touch target guideline as the benchmark for interactive elements.

## Completed Changes

### Auth Form (Sign In / Sign Up)
- Created custom `AuthPageLayout.tsx` wrapper with top-biased positioning (15vh from top)
- Created `SignInPage.tsx` and `SignUpPage.tsx` using the wrapper
- Updated `AppRoutes.tsx` to use custom auth pages while keeping StackHandler fallback
- Scale: `scale-125`, `max-w-lg`

### Sidebar Toggle Button
- `size-7` (28px) → `size-11` (44px) — meets Apple touch target guideline

### Landing Page
- Heading: `text-4xl sm:text-5xl` → `text-5xl sm:text-6xl`, added `font-semibold`
- Subtext: `text-lg sm:text-2xl` → `text-xl sm:text-2xl`, added `text-muted-foreground`
- Added `gap-4` between heading and subtext

### Sidebar Elements
- SidebarMenuButton default: `h-8` → `h-10`
- SidebarMenuButton lg variant: `h-12` → `h-14`, `text-sm` → `text-base`
- Document rows now use `size="lg"`
- Plan button and User button now use `size="lg"`

### Dropdown Menu
- Added `hover:bg-accent hover:text-accent-foreground` to DropdownMenuItem (was focus-only)
- Sign-out gets brownish hover: `hover:bg-muted-warm focus:bg-muted-warm`
- Increased padding: `py-1.5 px-2` → `py-2.5 px-3`

### Main Input Area
- Textarea: `min-h-120px` → `min-h-140px`, added `text-base`
- Paperclip button: `h-8 w-8` → `h-10 w-10`, icon `h-4 w-4` → `h-5 w-5`
- Start Listening button: added `size="lg"`, icons `h-4 w-4` → `h-5 w-5`

## Files Modified

- `frontend/src/pages/auth/AuthPageLayout.tsx` — New file, auth form wrapper
- `frontend/src/pages/auth/SignInPage.tsx` — New file, custom sign-in
- `frontend/src/pages/auth/SignUpPage.tsx` — New file, custom sign-up
- `frontend/src/routes/AppRoutes.tsx` — Added custom auth routes
- `frontend/src/components/ui/sidebar.tsx` — SidebarTrigger size, SidebarMenuButton variants
- `frontend/src/components/ui/dropdown-menu.tsx` — Hover styles, padding
- `frontend/src/components/documentSidebar.tsx` — Size variants, sign-out hover
- `frontend/src/components/header.tsx` — Font sizes, spacing
- `frontend/src/components/unifiedInput.tsx` — Textarea size, button sizes

## Additional: VoicePicker Scaling

Also scaled up the voice picker popover:
- Trigger: h-7 → h-9, text-xs → text-sm
- Popover: w-72 → w-96, max-h-80 → max-h-[28rem]
- Tabs: h-11, text-sm
- All internal elements: text-xs → text-sm, icons h-3 → h-4, padding increased

Note: Scaling everything proportionally doesn't show more voices at once, but it's less claustrophobic. Further improvements (showing more voices, better categorization, graying out unavailable voices) would need broader redesign.

## Remaining: Playback Page & Playbar

The playback content area and playbar could still benefit from sizing/UX review. At 100% zoom it's usable but 130% feels more comfortable.

### Playbar Issues Observed

**Layout inconsistency:**
- Voice selector is on the left
- Speed/Volume sliders are on the right
- Would be better if all controls were grouped consistently

**Label inconsistency:**
- "Speed" and "Volume" labels exist
- No "Voice" or "Settings" label
- Labels are far from their controls in some cases

**Mobile layout:**
- Needs dedicated review
- Controls may be cramped or awkwardly positioned

**General:**
- Legibility could be improved
- Touch targets for sliders may be small
- Could potentially increase overall playbar height

### Playbar Files (for future reference)
- `frontend/src/components/soundControl.tsx` — Main playbar component (~1000+ lines)
- Related: [[playbar-layout-redesign]] — Previous playbar work

## Sources

- **reference** — Apple Human Interface Guidelines (44pt/44px touch targets)
- **reference** — [[frontend-css-patterns]] for visual effect patterns
- **reference** — [[ui-polish-batch]] for color/visual decisions

## Gotchas

- Stack Auth's `<SignIn />` component has `fullPage` prop — set to `false` to control layout ourselves
- Radix dropdown hover is managed through focus for keyboard nav — need both `hover:` and `focus:` for full coverage
- SidebarMenuButton size variants were updated globally — may affect other uses if any

## Considered & Rejected

- **Global CSS scale transform** — Would scale everything uniformly but create blurry text and affect layout calculations. Better to adjust individual sizing values.
