---
status: active
started: 2026-01-24
---

# Task: Usage Log Transparency

## Intent

Show users what consumed their tokens/characters recently — transparency for billing.

Display in account section: last 31 days of usage events (TTS synthesis, OCR tokens) so users can see "what cost me X tokens" rather than just aggregate numbers.

## Data Source

`UsageLog` table — already has per-event records with type, amount, description, created timestamp. 31-day retention now enforced via background cleanup task.

## Open Questions

- Granularity: per-event list vs daily aggregates?
- Breakdown display: show from_subscription/rollover/purchased split? (currently in `details` JSON)
- UI location: separate tab in account, or inline with current usage display?
