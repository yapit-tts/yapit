---
status: done
started: 2026-02-17
refs: [87fa0c9, 6ca67aa, 034f4d0]
---

# Task: Account Page Overhaul

## Intent

Rework the account page into a coherent, useful dashboard. Three pieces:

1. **Lifetime engagement stats** — persistent per-voice/per-model stats that survive document deletion. Replace the current ephemeral Block-based stats.
2. **Settings reorganization** — account page becomes canonical home for all settings. Playback dialog keeps only live-preview settings (theme, scroll, content width).
3. **Visual polish** — coherent layout, better hierarchy, less "random cards stacked vertically."

## Engagement Stats

Currently, account page stats (time listened, characters, documents) are computed from Block/Document tables — ephemeral data that vanishes when documents are deleted. UsageLog has 31-day retention. Neither supports lifetime tracking.

Needs a lightweight aggregation table incremented on each TTS result, persisting independently of document lifecycle.

Candidates for granularity:
- **Row-per-voice** (~10 rows per user): "your top voices" + totals. No trends.
- **Row-per-voice-per-day** (~300 rows/user/year): enables trend charts. Still small.

Increment hook goes in `record_usage()` (`yapit/gateway/usage.py`). Additive table, additive code path — zero risk to existing billing.

Open questions:
- Backfill from existing UsageLog (last 31 days) or start fresh?
- Per-voice is most interesting. Per-model is more technical. Per-day trends might be overbuilding.

## Settings Reorganization

Current state:
- **Playback dialog** (`settingsDialog.tsx`): appearance, dark theme variant, scroll on restore, live scroll tracking, content width, scroll position, sharing toggles
- **Account page** (`AccountPage.tsx`): sharing toggles only (duplicated)

Target:
- **Account page**: all settings (appearance, dark theme, scroll, content width, scroll position, sharing). Canonical location.
- **Playback dialog**: appearance + dark theme + scroll + content width + scroll position. Settings that benefit from live preview. Remove sharing toggles from here.

## Links

- `agent/research/2026-02-16-account-page-redesign.md` — research artefact
- `agent/tasks/usage-log-transparency.md` — billing transparency (done: subscription page breakdown)
- `034f4d0` — subscription page usage breakdown (shipped)
