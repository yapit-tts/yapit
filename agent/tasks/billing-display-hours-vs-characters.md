---
status: active
started: 2026-01-03
---

# Task: Billing Display - Hours vs Characters

## Issue

Currently displaying usage/limits as "~X hours" everywhere. Problem: actual listening time varies up to 4x depending on playback speed and model quality (TTS-1-Max uses 2x quota).

Example: "20 hours" at Plus tier becomes ~5 hours if listening at 2x speed with Max model.

## Related Fix

Usage tooltip shows "~0 hrs" when usage is low — should show "<1 hr" instead. In sidebar tooltip and subscription page.

## Options to Consider

- Keep hours with better explanation/footnotes
- Switch to characters everywhere (accurate but less intuitive)
- Hybrid: characters primary, hours parenthetical
- Something else?

## Files

- `frontend/src/pages/SubscriptionPage.tsx`
- `frontend/src/components/documentSidebar.tsx`

## Context

See [[pricing-strategy-rethink]] for billing design decisions.
