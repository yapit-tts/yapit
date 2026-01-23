# Logging

Loguru with two outputs: stdout (for Docker logs) + JSON file (persistent).

## Configuration

Set in `yapit/gateway/logging_config.py`:
- **stdout**: Colored, human-readable, INFO level
- **file**: JSON lines at `$LOG_DIR/gateway.jsonl`, rotation 100MB x 100 files = 10GB max

`LOG_DIR` is `/data/gateway/logs` in prod, `gateway/logs` in dev.

## Features

**Standard logging interception**: All Python standard library logging (uvicorn, sqlalchemy, httpx, etc.) is routed to loguru. This means library warnings/errors appear in our logs.

**Request ID**: Every HTTP request gets a unique `request_id` (8-char hex) attached via middleware. All logs within that request include this ID in `.record.extra.request_id`, enabling correlation.

**Unhandled exceptions**: Caught by FastAPI exception handler, logged with request context (method, path, user_id, request_id) before returning 500.

## Querying Logs

JSON format, queryable with jq:

```bash
# Recent errors
jq 'select(.record.level.name == "ERROR")' gateway.jsonl

# Logs from specific module
jq 'select(.record.name | contains("billing"))' gateway.jsonl

# Correlate by request_id
jq 'select(.record.extra.request_id == "a1b2c3d4")' gateway.jsonl

# Correlate by user_id
jq 'select(.record.extra.user_id == "user_123")' gateway.jsonl

# Library logs (uvicorn, etc.)
jq 'select(.record.name | startswith("uvicorn"))' gateway.jsonl

# Warnings
jq 'select(.record.level.name == "WARNING")' gateway.jsonl
```

## What to Log

- **Metrics DB**: Quantitative events (latencies, counts, cache stats)
- **Log files**: Qualitative details (tracebacks, auth failures, webhook payloads)

Don't duplicate - if it's a countable event, it goes to metrics. If it's debugging context, it goes to logs.
