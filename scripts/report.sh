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

# Build context
if $AFTER_DEPLOY; then
    EXTRA_CONTEXT="CONTEXT: You were triggered shortly after a deploy. Focus on: Are there new errors since the deploy? Any anomalies compared to before?"
else
    EXTRA_CONTEXT="CONTEXT: Daily health check. Look for patterns, anomalies, degradation."
fi

# The analysis prompt
read -r -d '' PROMPT << 'EOF' || true
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
- **Logs**: gateway-data/logs/*.jsonl (JSON lines, multiple rotated files)

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

## What to Analyze

### Errors (should be near zero for system errors)
- `*_error` events — what failed and why?
- `job_dlq` — ANY entry is a red flag, something is systematically broken
- `job_requeued` — occasional is fine (transient), sustained pattern = worker issues
- ERROR level in logs — stack traces, exceptions

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

## What's Normal vs Concerning

| Metric | Normal | Concerning |
|--------|--------|------------|
| DLQ entries | 0 | Any (investigate immediately) |
| Error rate (system) | 0% | >0% sustained |
| Queue depth | <10 | >20 sustained |
| Queue wait (TTS) | <15s | >25s (overflow imminent) |
| Queue wait (YOLO) | <5s | >8s |
| Requeues | Rare/isolated | Pattern (same worker, same error) |
| Overflow usage | Occasional spikes | Constant (capacity issue) |

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

Don't request live/interactive prod access — that's out of scope by design.
EOF

echo "Running Claude analysis..."
message=$(claude -p "$PROMPT" \
    --allowedTools "Read,Bash(jq:*),Bash(grep:*),Bash(cat:*),Bash(head:*),Bash(tail:*),Bash(duckdb:*),Bash(wc:*),Bash(sort:*),Bash(uniq:*),Bash(ls:*)" \
    --append-system-prompt "$EXTRA_CONTEXT" \
    2>&1) || {
    echo "Claude analysis failed: $message"
    exit 1
}

# Save full report
REPORT_FILE="$REPORT_DIR/report-$(date +%Y-%m-%d-%H%M%S).md"
echo "$message" > "$REPORT_FILE"
echo "Report saved to: $REPORT_FILE"
echo ""
echo "$message"

# Send to Discord if webhook configured
if [[ -n "${DISCORD_WEBHOOK_URL:-}" ]]; then
    echo ""
    echo "Sending to Discord..."

    # Discord has 2000 char limit
    if [[ ${#message} -gt 1900 ]]; then
        discord_message="${message:0:1800}

... (truncated, full: $REPORT_FILE)"
    else
        discord_message="$message"
    fi

    curl -s -X POST "${DISCORD_WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"content\": $(echo "$discord_message" | jq -Rs .)}" || {
        echo "Discord webhook failed (continuing anyway)"
    }
    echo "Sent to Discord."
else
    echo "(DISCORD_WEBHOOK_URL not set, skipping Discord)"
fi
