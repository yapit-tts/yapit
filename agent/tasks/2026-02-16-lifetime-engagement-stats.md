---
status: pending-evaluation
---

# Task: Lifetime Engagement Stats

## Intent

Give users persistent, meaningful stats about their listening habits — which voices they prefer, how much they've listened over time, per-model breakdowns. The kind of stats that make you feel invested ("you've listened to 14 hours of Alloy").

Currently, the account page stats (time listened, characters, documents) are computed from Block/Document tables — ephemeral data that vanishes when documents are deleted. UsageLog has 31-day retention. Neither supports lifetime engagement tracking.

## What This Would Require

A lightweight aggregation table (e.g. `UserEngagementStats`) that gets incremented on each TTS result and persists independently of document lifecycle. Candidates:

- Per-voice totals: voice_id, total_characters, total_duration_ms
- Per-model totals: model_slug, total_characters, total_duration_ms
- Per-type totals: usage_type, total_amount (for OCR tokens too)
- Possibly daily granularity for trend charts (rows per user/day/voice)

Trade-offs to evaluate:
- **Row-per-voice** (simple, ~10 rows per user): Enough for "your top voices" and total stats. No trend data.
- **Row-per-voice-per-day** (moderate, ~300 rows/user/year if daily active): Enables trend charts. Still small.
- **Just increment on record_usage**: Zero migration risk to existing billing logic. Additive table, additive code path.

## Open Questions

- Do we backfill from existing UsageLog (last 31 days) or start fresh?
- What stats actually matter to users? Per-voice is most interesting. Per-model is more technical. Per-day trends are nice but might be overbuilding.
- How does this interact with account page redesign? These stats would replace the current ephemeral Block-based stats.

## Links

- `agent/research/2026-02-16-account-page-redesign.md` — research on account page + usage transparency
- `agent/tasks/usage-log-transparency.md` — related billing transparency task
- `yapit/gateway/usage.py:287` — `record_usage()` where increment hook would go
