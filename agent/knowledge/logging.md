
# Logging

Loguru with two outputs: stdout (for Docker logs) + JSON file (persistent).

## Configuration

Set in `yapit/gateway/__init__.py`:
- **stdout**: Colored, human-readable, INFO level
- **file**: JSON lines at `$LOG_DIR/gateway.jsonl`, rotation 50MB x 20 files = 1GB max

`LOG_DIR` is `/data/gateway/logs` in prod, `gateway/logs` in dev.

## Querying Logs

JSON format, queryable with jq:

```bash
# Recent errors
cat gateway-data/logs/gateway.jsonl | jq 'select(.record.level.name == "ERROR")'

# Logs from specific module
cat gateway-data/logs/gateway.jsonl | jq 'select(.record.name | contains("billing"))'
```

## What to Log

- **Metrics DB**: Quantitative events (latencies, counts, cache stats)
- **Log files**: Qualitative details (tracebacks, auth failures, webhook payloads)

Don't duplicate - if it's a countable event, it goes to metrics. If it's debugging context, it goes to logs.

