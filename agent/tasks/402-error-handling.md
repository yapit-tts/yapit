---
status: active
started: 2026-01-03
---

# Task: 402 Payment Required Error Handling

## Issue

When API returns 402 (hit usage limit), need proper error UI. Currently probably shows generic error or fails silently.

Should show clear message about hitting limit with link to upgrade.

## Files

- `frontend/src/pages/PlaybackPage.tsx` — error handling
- `frontend/src/api.tsx` — API layer
