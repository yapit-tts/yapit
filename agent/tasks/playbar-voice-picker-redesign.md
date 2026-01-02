---
status: done
started: 2026-01-01
completed: 2026-01-01
---

# Task: Playbar & Voice Picker Redesign

Continues from [[ui-sizing-scale-up]]. That task scaled up sizing but identified playbar/voice picker as needing deeper design work.

## Intent

**User's mental model:** The playbar and voice picker work functionally, but have UX issues. Not just a sizing problem — the information architecture and layout need holistic rethinking. Mobile is a priority.

## Completed Changes

### 1. HIGGS Tab Hidden
- Added `const SHOW_HIGGS_TAB = false;` constant
- Conditionally renders tab and content
- Code preserved for future re-enablement

### 2. Inworld Voice Two-Line Layout
- `VoiceRow` component now uses two-line layout when `detail` prop is present
- Name (bold) on first line, description on second line
- Single-line layout preserved for Kokoro voices (no descriptions)
- Much cleaner, more readable voice list

### 3. Mobile Expanded Section Redesign
- Removed "Speed" and "Volume" labels (consistent with VoicePicker having no label)
- Voice picker now centered
- Sliders now full-width (`flex-1` instead of `w-32`)
- Settings icon bigger via new `size="lg"` prop on SettingsDialog

### 4. Desktop Playbar Scaled Up
- Text: `text-xs` → `text-sm` (more readable)
- Speed value width: `w-10` → `w-12`
- Sliders: `w-24` → `w-32` (wider)
- Volume icon: `h-4 w-4` → `h-5 w-5`
- Gaps increased for better spacing

## Files Modified

- `frontend/src/components/voicePicker.tsx` — HIGGS hiding, two-line VoiceRow layout
- `frontend/src/components/soundControl.tsx` — Mobile/desktop layout improvements
- `frontend/src/components/settingsDialog.tsx` — Added `size` prop for larger mobile trigger

## Relevant Files

- `frontend/src/components/voicePicker.tsx` — Voice picker component
- `frontend/src/components/soundControl.tsx` — Main playbar
- `frontend/src/components/settingsDialog.tsx` — Settings dialog with size variant

## Sources

- **reference** — [[ui-sizing-scale-up]] — Previous sizing work
- **reference** — [[playbar-layout-redesign]] — Previous layout work, mobile expand pattern

## Gotchas

- SettingsDialog's `size="lg"` prop only affects the trigger button size, not the dialog content
- Mobile detection relies on `useSidebar().isMobile` which checks viewport breakpoint

## Considered & Rejected

- **Truncate descriptions with tooltip** — Adds hover layer, doesn't work on mobile
- **Description on hover only** — Same issues, less discoverable
- **Add labels to all controls** — Would clutter, sliders are self-explanatory
