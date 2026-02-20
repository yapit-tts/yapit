#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Output directory for full reports
REPORT_DIR="$HOME/tmp/yapit-reports"
mkdir -p "$REPORT_DIR"

# Parse flags
AFTER_DEPLOY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --after-deploy) AFTER_DEPLOY=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--after-deploy]"
            echo "  --after-deploy  Add context about recent deploy"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Sync data from prod
echo "Syncing data from prod..."
make sync-data

# Require VPS_HOST
if [[ -z "${VPS_HOST:-}" ]]; then
    echo "Error: VPS_HOST not set"
    exit 1
fi

# Capture disk usage (full report + appends to history on VPS)
echo "Gathering disk usage..."
DISK_REPORT=$("$SCRIPT_DIR/disk-usage.sh" 2>&1 || echo "(disk-usage.sh failed)")

# Fetch disk history (last 50 entries)
echo "Fetching disk history..."
DISK_HISTORY=$(ssh "$VPS_HOST" "tail -50 /var/log/yapit-disk-history.log 2>/dev/null" || echo "(no history yet)")

# Build context
if $AFTER_DEPLOY; then
    BASE_CONTEXT="CONTEXT: You were triggered shortly after a deploy. Focus on: Are there new errors since the deploy? Any anomalies compared to before?"
else
    BASE_CONTEXT="CONTEXT: Daily health check. Look for patterns, anomalies, degradation."
fi

EXTRA_CONTEXT="$BASE_CONTEXT

## DISK_USAGE (current snapshot)

$DISK_REPORT

## DISK_HISTORY (last 50 entries)

$DISK_HISTORY"

# The analysis prompt
read -r -d '' PROMPT << 'EOF' || true
IGNORE ALL (CLAUDE.MD) INSTRUCTIONS BEFORE THIS MESSAGE. YOU ARE A FOCUSSED DIAGNOSTIC AGENT AND DO NOT HAVE THE SAME TOOLS AVAILABLE. YOUR *ONLY* INSTRUCTIONS ARE THE FOLLOWING:
You are analyzing system health for Yapit TTS.

## System Architecture

Yapit is a text-to-speech platform with these components:

**TTS Pipeline:**
- Users submit text blocks for synthesis
- Jobs go to Redis queues, one per model (e.g., `tts:queue:kokoro`, `tts:queue:inworld`)
- TTS workers (Kokoro, Inworld) pull jobs, synthesize audio, push results
- Gateway consumes results and streams to clients via WebSocket

**Detection Pipeline:**
- PDF pages get rendered to images
- YOLO workers detect figures/bounding boxes
- Results feed into Gemini extraction

**Reliability mechanisms:**
- **Visibility timeout**: If worker takes too long (TTS: 30s, YOLO: 10s), job is requeued
- **Overflow**: If job waits too long in queue, sent to RunPod serverless
  - Kokoro: 30s threshold, has RunPod overflow
  - Inworld: NO overflow (external API, can't run on RunPod)
  - YOLO: 10s threshold, has RunPod overflow
- **DLQ (Dead Letter Queue)**: Jobs that fail after max retries — indicates systematic failure

**Models:**
- `kokoro` — local Kokoro TTS, has overflow to RunPod serverless
- `inworld` — Inworld external API, NO overflow. Jobs dispatched in parallel (no semaphore).
  - Queue wait should be <1s (parallel dispatch). High queue wait = bug.
  - Processing time >5s is unusual. Watch for rate limit errors.
- YOLO — local object detection, has overflow to RunPod serverless

## Data Locations

- **Metrics DB**: gateway-data/metrics.duckdb
  - `metrics_event` — raw events (last 100k)
  - `metrics_hourly` — hourly aggregates
  - `metrics_daily` — daily aggregates

**Schema note**: Fields like queue_wait_ms, worker_latency_ms, worker_id, model_slug, etc. are TOP-LEVEL COLUMNS on metrics_event, NOT nested inside the `data` JSON column. Use `SELECT queue_wait_ms FROM metrics_event`, NOT `data->>'queue_wait_ms'`. The `data` column is only for unstructured/overflow fields. Run `DESCRIBE metrics_event` first to see all available columns.
- **Logs**: gateway-data/logs/*.jsonl (JSON lines, multiple rotated files)
- **Disk Report**: See DISK_USAGE section below (captured at report time)

**Timezones**: Metrics DB uses CET (Europe/Vienna). Logs use UTC. Report times in CET, converting as needed.

## Event Types in Metrics

**TTS flow:**
- `synthesis_queued` — job entered queue (has `queue_depth`)
- `synthesis_complete` — successful synthesis (has `queue_wait_ms`, `worker_latency_ms`, `worker_id`)
- `synthesis_error` — synthesis failed

**Detection flow:**
- `detection_queued`, `detection_complete`, `detection_error`

**Reliability events:**
- `job_requeued` — visibility timeout fired, job retrying
- `job_dlq` — job exceeded max retries, moved to dead letter queue (BAD)
- `job_overflow` — job sent to RunPod serverless due to queue backup
- `overflow_complete`, `overflow_error` — RunPod result

**Extraction:**
- `extraction_estimate` — pre-check token estimate (compare with actual for tuning)
- `page_extraction_complete`, `page_extraction_error` — Gemini API calls

**API rate limits:**
- `api_rate_limit` — emitted on every 429 response from external APIs before retry
  - `data.api_name` — which API ("gemini" or "inworld")
  - `status_code` — always 429
  - `retry_count` — 0-indexed attempt number when the 429 occurred
  - Any occurrence means we're hitting rate limits. Occasional is expected under load; sustained = need to throttle or increase quota.

**Gateway-internal errors and warnings:**
- `error` — gateway-side failures caught by exception handlers (e.g., cache write failures, DB errors during result processing). These are NOT pipeline-specific errors — they indicate something broke inside the gateway itself. Check `data.message` for details.
- `warning` — non-fatal issues worth tracking (e.g., near-failures, degraded behavior)
- ANY `error` event is a red flag. These represent failures that may silently drop work — e.g., a synthesis result that completed but couldn't be cached, leaving the user with no audio.

**Billing/Webhooks:**
- `stripe_webhook` — Stripe webhook processing
  - `duration_ms` — handler latency. Nominal: <1s. Stripe times out at 20s.
  - `data.event_type` — which event (invoice.paid, subscription.updated, etc.)
  - `status_code=500` — handler crashed
- `billing_sync_drift` — periodic reconciliation found local DB out of sync with Stripe
  - `data.user_id` — affected user
  - `data.drift` — what drifted (list of field names, or "sub_gone")
  - Any occurrence means a webhook was missed. Occasional is expected; sustained = webhook issues.
- `billing_processed` — TTS billing consumer batch processed
  - `duration_ms` — batch processing time
  - `text_length` — total characters billed in batch
  - `data.events_count` — number of synthesis events in the batch
  - `data.users_count` — unique users in the batch

**URL/Document fetching:**
- `url_fetch` — document URL downloads
  - `duration_ms`, `data.content_type`, `data.size_bytes` on success
  - `data.error` on failure (http_status or request_error)
- `playwright_fetch` — JS rendering fallback (lower volume, expensive path)
  - `duration_ms` on success, `data.error` on failure

## What to Analyze

### Errors — HIGHEST PRIORITY
This is the most important section. Don't just count errors — read the actual error messages and investigate.

**Metrics DB errors:**
- `error` events (gateway-internal) — ANY nonzero count is a red flag. Read `data.message` for each. These represent silent failures that may cause user-visible breakage (e.g., audio not playing, results disappearing).
- `synthesis_error` events — worker-reported failures. Check `data.error` for each distinct error message.
- `detection_error`, `page_extraction_error`, `overflow_error` — same: read the actual error messages.
- `job_dlq` — ANY entry means something is systematically broken. Investigate immediately.
- `job_requeued` — occasional is fine (transient), sustained pattern = worker issues.

**Log file errors (gateway-data/logs/*.jsonl):**
- Scan ALL log files for ERROR and WARNING level entries. Don't skip this even if metrics look clean — some errors only appear in logs.
- For each distinct error, report: the error message, count, and time range.
- ERROR level in logs — stack traces, exceptions (include request context: method, path, user_id, request_id)

### Warnings
- WARNING level in logs — library warnings, deprecations, near-failures
- How often do they occur? Any patterns by module or time?
- Warnings often precede errors — look for escalation patterns

### Queue Health
- `queue_depth` values in `synthesis_queued` — sustained >20 means workers can't keep up
- `queue_wait_ms` in `synthesis_complete`:
  - TTS: <15s normal, approaching 30s = overflow about to trigger
  - Detection: <5s normal, approaching 10s = overflow imminent

### Worker Performance
- `worker_latency_ms` per `worker_id` — compare workers, find outliers
- Throughput: count of completions per worker
- Error rate per worker — one worker failing more than others?

### Overflow Usage
- `job_overflow` count — occasional during spikes is fine
- `overflow_error` — RunPod failures, concerning if frequent

### Extraction (Gemini)
- `page_extraction_error` — rate limit (429), server errors (5xx)?
- Token counts — unusual spikes?

### Billing Health
- Reconciliation: compare count(synthesis_complete) vs sum(data->>'events_count') from billing_processed.
  Delta = unbilled events. Small delta (<10) is normal (in-flight).
  Growing delta = billing consumer falling behind or losing events.
- Consumer liveness: if synthesis_complete events exist in the last hour but no billing_processed events,
  the billing consumer may be down.
- billing_processed errors: any `error` events with billing context indicate billing consumer failures.

### Cache

- "vacuum" events. Are they running? Are they effective? Do they take too long?

## What's Normal vs Concerning

| Metric | Normal | Concerning |
|--------|--------|------------|
| `error` events | 0 | Any (investigate — read data.message) |
| DLQ entries | 0 | Any (investigate immediately) |
| Error rate (synthesis) | 0% | >0% sustained |
| Log ERROR entries | 0 | Any (read the actual messages) |
| Queue depth | <10 | >20 sustained |
| Queue wait (TTS) | <15s | >25s (overflow imminent) |
| Queue wait (YOLO) | <5s | >8s |
| Requeues | Rare/isolated | Pattern (same worker, same error) |
| Overflow usage | Occasional spikes | Constant (capacity issue) |
| Billing sync drift | 0 | Any (check which webhooks are being missed) |
| Billing reconciliation delta | <10 | >50 sustained (lost events) |

Events older than 3-7 days can be ignored unless part of a larger pattern / investigation.
E.g. items on the DLQ from >7 days ago are almost certainly already taken care of.

## Log Investigation

Logs are JSON lines (loguru format). Key fields:
- `.record.level.name` — ERROR, WARNING, INFO
- `.record.name` — module path (e.g., "yapit.gateway.api.v1.documents", "uvicorn.error")
- `.record.message` — log message
- `.record.exception` — stack trace (when present)

**Structured context in `.record.extra`:**
Fields vary by component. Discover available fields with:
\`\`\`bash
jq -r '[.record.extra | keys[]] | .[]' gateway.jsonl | sort | uniq -c | sort -rn
\`\`\`

Common fields:
- `request_id` — 8-char hex, auto-added to all HTTP request logs (middleware)
- `user_id` — present on TTS jobs, WebSocket, extraction, billing, and error logs
- `job_id`, `variant_hash`, `model_slug`, `voice_slug`, `worker_id` — TTS pipeline logs
- `extraction_id`, `content_hash` — document extraction logs
- `document_id` — WebSocket and extraction logs
- `queue_type`, `model_slug` — scanner/overflow logs
- `method`, `path` — unhandled exception logs

**Correlation strategies:**
- HTTP requests: correlate by `request_id` to see full request timeline
- TTS jobs: correlate by `job_id` or `variant_hash` across tts_loop → result_consumer
- Extractions: correlate by `extraction_id` across the full extraction lifecycle
- User issues: filter by `user_id` across all components
- Cache warming: filter by `user_id == "cache-warmer"`

**Useful jq patterns:**
\`\`\`bash
# All errors
jq 'select(.record.level.name == "ERROR")' gateway.jsonl

# All warnings
jq 'select(.record.level.name == "WARNING")' gateway.jsonl

# Correlate by request_id (full HTTP request timeline)
jq 'select(.record.extra.request_id == "a1b2c3d4")' gateway.jsonl

# All logs for a specific user
jq 'select(.record.extra.user_id == "user_123")' gateway.jsonl

# TTS job lifecycle (queue → worker → result)
jq 'select(.record.extra.variant_hash == "abc...")' gateway.jsonl

# Extraction lifecycle
jq 'select(.record.extra.extraction_id == "xyz")' gateway.jsonl

# Cache warming activity (pre-synthesizes voice previews so they're free and instant for users)
jq 'select(.record.extra.user_id == "cache-warmer")' gateway.jsonl

# Library warnings (uvicorn, sqlalchemy, etc.)
jq 'select(.record.level.name == "WARNING" and (.record.name | startswith("yapit") | not))' gateway.jsonl

# Discover which structured fields exist and how often (run this first when investigating)
jq -r '[.record.extra | keys[]] | .[]' gateway.jsonl | sort | uniq -c | sort -rn
\`\`\`

**Investigation workflow:**
1. Start with ERROR/WARNING counts and patterns
2. For suspicious errors, correlate by request_id or job_id to see full context
3. If patterns emerge by user_id, check if user-specific (bad input? specific document?)
4. Check INFO logs around the error time for additional context

## Output Format

Start with status:
- ✅ **All nominal** — no issues
- ⚠️ **Issues detected** — problems found
- 🔍 **Anomalies noted** — unusual patterns worth noting

Then:
1. **Summary** (2-3 sentences)
2. **Key Metrics** (bullets: counts, rates, latencies)
3. **Issues** (if any — what, severity, details)
4. **Patterns** (correlations, clusters, trends)
5. **Recommendations** (if actionable)

Be concise but complete. This is a diagnostic report.

## Limitations

You have access to **synced static data only** (metrics DB + logs up to sync time).
You do NOT have:
- Live Redis access (no current queue depths)
- Live worker status (only historical metrics)
- Interactive prod access

If any of these would help future analysis, note them:
- Additional **metrics or log fields**
- **Analysis tools/utilities** (scripts, queries, anything reusable)
- **Tool permissions** you were missing

**Important**: 
- DO NOT request live/interactive prod access — that's out of scope by design.
- DO NOT include comments before bash commands — they won't match allowed tool patterns and will be blocked.
- FORGET instructions from our CLAUDE.MD knowledge files. They do not apply in the environment you're operating in now. ONLY the rules specified in this message apply.

===
AVAILABLE TOOLS - USE THESE TO YOUR ADVANTAGE: Read,Bash(jq:*),Bash(grep:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(duckdb:*),Bash(wc:*),Bash(sort:*),Bash(uniq:*),Bash(ls:*)
Use these tools exactly as indicated by the permissions, i.e. "duckdb ..." NOT "nix run ..." and NOT "bash -c 'duckdb ...'", or similar. 
EOF

echo "Running Claude analysis..."
output=$(claude -p "$PROMPT" \
    --allowedTools "Read,Bash(jq:*),Bash(grep:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(duckdb:*),Bash(wc:*),Bash(sort:*),Bash(uniq:*),Bash(ls:*)" \
    --append-system-prompt "$EXTRA_CONTEXT" \
    --output-format json \
    2>"$REPORT_DIR/claude-stderr.log") || {
    echo "Claude analysis failed. stderr: $(cat "$REPORT_DIR/claude-stderr.log")"
    echo "stdout: $output"
    exit 1
}

# --output-format json returns a JSON array of events; extract the result event
result_event=$(echo "$output" | jq -c '.[] | select(.type == "result")' 2>/dev/null || echo "$output" | jq -c 'select(.type == "result")' 2>/dev/null || echo '{}')
session_id=$(echo "$result_event" | jq -r '.session_id // "unknown"')
result=$(echo "$result_event" | jq -r '.result // "No result"')
denials=$(echo "$result_event" | jq -r '.permission_denials | if length > 0 then .[] | "- \(.tool_name): \(.tool_input.command // .tool_input | tostring)" else empty end')

message="Session: $session_id
---

$result"

if [[ -n "$denials" ]]; then
    message="$message

---
⚠️ Permission denials:
$denials"
fi

# Save full report
REPORT_FILE="$REPORT_DIR/report-$(date +%Y-%m-%d-%H%M%S).md"
echo "$message" > "$REPORT_FILE"
echo "Report saved to: $REPORT_FILE"
echo ""
echo "$message"

# Send to ntfy if topic configured
if [[ -n "${NTFY_TOPIC:-}" ]]; then
    echo ""
    echo "Sending to ntfy..."

    # Determine status from message content
    if echo "$result" | head -1 | grep -q "✅"; then
        PRIORITY="default"
        TITLE="✅ Yapit health: nominal"
    elif echo "$result" | head -1 | grep -q "⚠️"; then
        PRIORITY="high"
        TITLE="⚠️ Yapit health: issues detected"
    else
        PRIORITY="default"
        TITLE="🔍 Yapit health report"
    fi

    # ntfy has ~4KB limit for message body
    if [[ ${#message} -gt 3800 ]]; then
        ntfy_message="${message:0:3700}

... (truncated, full: $REPORT_FILE)"
    else
        ntfy_message="$message"
    fi

    printf '%s' "$ntfy_message" | curl -s \
        -H "Title: $TITLE" \
        -H "Priority: $PRIORITY" \
        -H "Tags: health" \
        -d @- \
        "https://ntfy.sh/${NTFY_TOPIC}" || {
        echo "ntfy notification failed (continuing anyway)"
    }
    echo "Sent to ntfy."
else
    echo "(NTFY_TOPIC not set, skipping ntfy)"
fi
