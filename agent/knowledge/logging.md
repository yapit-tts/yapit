# Logging

Loguru with two outputs: stdout (for Docker logs) + JSON file (persistent).

## Configuration

Set in `yapit/gateway/logging_config.py`:
- **stdout**: Colored, human-readable, INFO level
- **file**: JSON lines at `$LOG_DIR/gateway.jsonl`, rotation 100MB x 100 files = 10GB max

`LOG_DIR` is `/data/gateway/logs` in prod, `gateway/logs` in dev.

## Features

**Standard logging interception**: All Python standard library logging (uvicorn, sqlalchemy, httpx, etc.) is routed to loguru. This means library warnings/errors appear in our logs.

**Request ID**: Every HTTP request gets a unique `request_id` (8-char hex) attached via middleware (`RequestContextMiddleware`). Uses `logger.contextualize()` so all logs within that request automatically include the ID in `.record.extra.request_id`.

**Structured context via `logger.bind()`**: Background tasks and long-lived connections (WebSocket, TTS workers, extraction, scanners) use `logger.bind()` to attach structured fields (user_id, job_id, variant_hash, etc.) to `.record.extra`. These fields are queryable with jq in the JSON logs.

**Unhandled exceptions**: Caught by FastAPI exception handler, logged with structured fields (request_id, user_id, method, path).

## Structured Fields by Component

| Component | Fields in `.record.extra` |
|-----------|--------------------------|
| HTTP requests | `request_id` (auto via middleware) |
| Unhandled exceptions | `request_id`, `user_id`, `method`, `path` |
| TTS worker (`tts_loop`) | `job_id`, `user_id`, `model_slug`, `voice_slug`, `variant_hash`, `worker_id` |
| Result consumer | `variant_hash`, `user_id`, `model_slug`, `voice_slug`, `job_id`, `worker_id` |
| WebSocket (`ws.py`) | `user_id`, `document_id` |
| Extraction (`documents.py`) | `extraction_id`, `user_id`, `content_hash` |
| Visibility scanner | `job_id`, `queue_type`, `model_slug` |
| Overflow scanner | `queue_type`, `model_slug`, `job_id` |
| Inworld adapter | `model_id`, `voice_id` |
| Synthesis timeout | `user_id`, `model_slug`, `voice_slug`, `variant_hash`, `document_id` |
| Usage/billing debt | `user_id`, `usage_type` |
| Stripe webhooks (`billing.py`) | `event_type`, `stripe_event_id`, `user_id`, `stripe_sub_id`, `stripe_customer_id`, `plan_tier`, `invoice_id`, `billing_reason` |

## Adding Structured Logging

Use `logger.bind()` to attach fields to individual log calls:
```python
logger.bind(user_id=user_id, job_id=job_id).info("Job completed")
```

For broader scopes (e.g., a background task function), create a bound logger once:
```python
ext_log = logger.bind(extraction_id=eid, user_id=uid, content_hash=hash)
ext_log.info("Starting")
ext_log.info("Done")
```

`logger.contextualize()` is a context manager alternative — all logger calls inside the `with` block inherit the fields. Used by the request ID middleware. Prefer `logger.bind()` when it avoids re-indenting existing code.

## Querying Logs

```bash
# Discover which structured fields exist
jq -r '[.record.extra | keys[]] | .[]' gateway.jsonl | sort | uniq -c | sort -rn

# Correlate by request_id (full HTTP request timeline)
jq 'select(.record.extra.request_id == "a1b2c3d4")' gateway.jsonl

# All logs for a user
jq 'select(.record.extra.user_id == "user_123")' gateway.jsonl

# TTS job lifecycle
jq 'select(.record.extra.variant_hash == "abc...")' gateway.jsonl

# Extraction lifecycle
jq 'select(.record.extra.extraction_id == "xyz")' gateway.jsonl

# Cache warming (pre-synthesizes voice previews)
jq 'select(.record.extra.user_id == "cache-warmer")' gateway.jsonl

# Errors / warnings
jq 'select(.record.level.name == "ERROR")' gateway.jsonl
jq 'select(.record.level.name == "WARNING")' gateway.jsonl
```

## What to Log

- **Metrics DB**: Quantitative events (latencies, counts, cache stats)
- **Log files**: Qualitative details (tracebacks, auth failures, webhook payloads)

Don't duplicate - if it's a countable event, it goes to metrics. If it's debugging context, it goes to logs.
