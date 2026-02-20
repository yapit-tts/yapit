---
status: active
---

# Close Observability Gaps

## Intent

Add missing `api_rate_limit` signal and clean up dead observability code found during analysis.

## Work

### 1. `api_rate_limit` metric

Emit on every 429 from Gemini (`gemini.py:_call_gemini_with_retry`) and Inworld (`inworld.py:synthesize`) before retrying. Fields: status_code, retry_count, data.api_name.

Both run in the gateway process (Inworld dispatchers are gateway-side), so `log_event` works directly.

### 2. Clean up dead weight

- Remove `eviction_triggered` metric event from `_handle_cursor_moved` — just logs normal user navigation, not actionable.
- Remove `cursor` field from `WSSynthesizeRequest` — dead code, never read by backend. Frontend sets it to last block in batch (not the playback cursor) due to microtask batching, but it doesn't matter since nothing reads it.

### 3. Update daily report prompt

Add `api_rate_limit` event type to `scripts/report.sh`.

## Assumptions

- No schema migration needed — `api_rate_limit` fits existing `metrics_event` columns + `data` JSONB.
- No frontend changes needed for the metric. Frontend WS message schema change (dropping `cursor`) is backwards-compatible (backend just stops expecting it).

## Considered & Rejected

- **`time_to_first_audio` metric** — Average TTFA equals average block synthesis latency, already captured by `synthesis_complete.total_latency_ms`. A dedicated client-side TTFA metric (via new WS message type) would be overengineered for redundant data.

## Done When

- `api_rate_limit` emitting in dev on 429s from both Gemini and Inworld
- Dead code removed (eviction_triggered event, synthesize cursor field)
- Daily report prompt updated
