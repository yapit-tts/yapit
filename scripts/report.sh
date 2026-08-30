#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Every report ever written. Under ~/logs, which is backed up and never swept:
# the laptop's yapit dashboard lists months of these.
REPORT_DIR="$HOME/logs/yapit-reports"
mkdir -p "$REPORT_DIR"

UNIT=yapit-health-report

# Which verdict the report opened with — the one thing that decides whether this
# notifies. The prompt asks for the status line first, but an agent sometimes
# writes a sentence in front of it, so the first line carrying any of the three
# markers decides, and a line carrying two of them reads as the louder one.
# Reads all of its input even after it has decided, so that whatever is writing
# to it never takes a SIGPIPE mid-report — a report long enough to fill a pipe
# would otherwise kill this script between saving itself and notifying.
classify() {  # report text on stdin -> issues|anomalies|nominal|unknown
    local line verdict="" n=0
    while IFS= read -r line; do
        n=$((n + 1))
        if [[ -z "$verdict" && "$n" -le 20 ]]; then
            case "$line" in
                *⚠*) verdict=issues ;;
                *🔍*) verdict=anomalies ;;
                *✅*) verdict=nominal ;;
            esac
        fi
    done
    echo "${verdict:-unknown}"
}

# What the report did, for anyone reading later: run-log keeps one line per run
# in ~/logs/runs/$UNIT.jsonl. The overdue watchdog reads it to tell "ran, nothing
# to report" from "has not run in days", and the yapit dashboard lists it.
log_run() {  # outcome [reason] [stats-json]
    local stats="${3:-}"
    [[ -n "$stats" ]] || stats='{}'
    if ! command -v run-log >/dev/null 2>&1; then
        echo "run-log is not on PATH — this run goes unrecorded, and the watchdog will call $UNIT overdue" >&2
        return 0
    fi
    run-log "$UNIT" "$1" --reason "${2:-}" --stats "$stats" \
        || echo "run-log failed — this run goes unrecorded" >&2
    return 0
}

# Parse flags
AFTER_DEPLOY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --after-deploy) AFTER_DEPLOY=true; shift ;;
        --classify) classify; exit 0 ;;
        -h|--help)
            echo "Usage: $0 [--after-deploy | --classify]"
            echo "  --after-deploy  Add context about recent deploy"
            echo "  --classify      Read a report on stdin, print the verdict that decides whether it notifies"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# A run that dies anywhere below says so in the run log, so a report that stopped
# happening is visible as itself rather than as a gap.
fail_reason=""
finish() {
    local rc=$?
    [[ "$rc" -eq 0 ]] && return 0
    log_run fail "${fail_reason:-report.sh exited $rc before finishing — journalctl --user -u $UNIT}"
}
trap finish EXIT

# Sync data from prod
echo "Syncing data from prod..."
make sync-data

# Load env vars from .env (VPS_HOST, CLOUDFLARE_API_TOKEN, etc.).
# These win over anything already exported.
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

if [[ -z "${VPS_HOST:-}" ]]; then
    echo "Error: VPS_HOST not set (set in env or .env)"
    exit 1
fi

# Metrics pipeline freshness (deterministic staleness check on the just-synced data)
echo "Checking metrics freshness..."
METRICS_FRESHNESS=$(uv run --with duckdb python "$SCRIPT_DIR/metrics_freshness.py" 2>&1 || echo "(metrics_freshness.py failed — treat metrics freshness as UNKNOWN and investigate)")

# Capture disk usage (full report + appends to history on VPS)
echo "Gathering disk usage..."
DISK_REPORT=$("$SCRIPT_DIR/disk-usage.sh" 2>&1 || echo "(disk-usage.sh failed)")

# Fetch disk history (last 50 entries)
echo "Fetching disk history..."
DISK_HISTORY=$(ssh "$VPS_HOST" "tail -50 /var/log/yapit-disk-history.log 2>/dev/null" || echo "(no history yet)")

# Capture Cloudflare analytics (edge traffic, cache, errors, 504 diagnostics)
echo "Gathering Cloudflare analytics..."
CF_REPORT=$(uv run "$SCRIPT_DIR/cf_analytics.py" --plain 2>&1 || echo "(cf_analytics.py failed — is CLOUDFLARE_API_TOKEN set?)")

# Capture proxy diagnostics (Stack Auth + Traefik from VPS container logs)
echo "Gathering proxy diagnostics..."
PROXY_REPORT=$(uv run "$SCRIPT_DIR/proxy_diagnostics.py" 2>&1 || echo "(proxy_diagnostics.py failed — is VPS_HOST set and SSH working?)")

# Billing reconciliation (synthesis events vs billing events)
echo "Running billing reconciliation..."
BILLING_RECON=$(uv run "$SCRIPT_DIR/billing_reconciliation.py" --days 14 2>&1 || echo "(billing_reconciliation.py failed)")

# Recent commits + deploys, so incidents can be checked against the fix that landed after them
GIT_LOG=$(git log -30 --date=format-local:'%Y-%m-%d %H:%M' --format='%ad  %h  %s')
DEPLOY_LOG=$(tail -10 "$PROJECT_DIR/.deploys.log" 2>/dev/null || echo "(no deploy log)")

# Build context
if $AFTER_DEPLOY; then
    BASE_CONTEXT="CONTEXT: You were triggered shortly after a deploy. Focus on: Are there new errors since the deploy? Any anomalies compared to before?"
else
    BASE_CONTEXT="CONTEXT: Daily health check. Look for patterns, anomalies, degradation."
fi

EXTRA_CONTEXT="$BASE_CONTEXT

## METRICS FRESHNESS (last metrics event age vs log activity, pre-computed)

$METRICS_FRESHNESS

## DISK_USAGE (current snapshot)

$DISK_REPORT

## DISK_HISTORY (last 50 entries)

$DISK_HISTORY

## CLOUDFLARE ANALYTICS (edge traffic, cache, errors, 504 diagnostics)

$CF_REPORT

## PROXY DIAGNOSTICS (Stack Auth + Traefik from VPS container logs)

$PROXY_REPORT

## BILLING RECONCILIATION (synthesis events vs billing events, pre-computed)

$BILLING_RECON

## RECENT COMMITS (last 30, newest first, local time)

$GIT_LOG

## DEPLOYS (last 10, local time — when a commit reached prod; FAILED = deploy aborted, code did not ship)

$DEPLOY_LOG"

# The analysis prompt
read -r -d '' PROMPT << 'EOF' || true
You are a diagnostic agent analyzing system health for Yapit TTS.

**Infra note (2026-08-02):** prod migrated to a smaller Hetzner server (CPX32: 4 vCPU, 8 GB RAM + 8 GB swap, 160 GB disk). kokoro-cpu replicas 4→2, yolo-cpu 4→1 (external GPU workers unchanged); cache caps now audio 30 GB / extraction 30 GB / document 5 GB. Disk history restarted with the new server — "(no history yet)" or a short history is expected, not data loss. Don't compare absolute disk totals or worker counts against pre-migration values.

## System Architecture

Yapit is a text-to-speech platform with these components:

**TTS Pipeline:**
- Users submit text blocks for synthesis
- Jobs go to Redis queues, one per model (e.g., `tts:queue:kokoro`)
- TTS workers pull jobs, synthesize audio, push results
- Gateway consumes results and streams to clients via WebSocket

**Detection Pipeline:**
- PDF pages get rendered to images
- YOLO workers detect figures/bounding boxes
- Results feed into Gemini extraction

**Reliability mechanisms:**
- **Visibility timeout**: If worker takes too long (TTS: 20s, YOLO: 10s), job is requeued
- **DLQ (Dead Letter Queue)**: Jobs that fail after max retries — indicates systematic failure

**Models:**
- `kokoro` — local Kokoro TTS
- `openai-tts` — OpenAI-compatible TTS API. Jobs dispatched in parallel. Currently not configured in production.
- YOLO — local object detection

## Data Locations

- **Metrics DB**: data/metrics.duckdb
  - `metrics_event` — raw events (30-day retention)
  - `metrics_hourly` — hourly aggregates
  - `metrics_daily` — daily aggregates

**Schema note**: Fields like queue_wait_ms, worker_latency_ms, worker_id, model_slug, etc. are TOP-LEVEL COLUMNS on metrics_event, NOT nested inside the `data` JSON column. Use `SELECT queue_wait_ms FROM metrics_event`, NOT `data->>'queue_wait_ms'`. The `data` column is only for unstructured/overflow fields. Run `DESCRIBE metrics_event` first to see all available columns.
- **Logs**: data/logs/*.jsonl (JSON lines, multiple rotated files)
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

**Document extraction:**
- `document_extraction_complete` — emitted for every document extraction (all paths)
  - `processor_slug` — which method: pymupdf, epub, passthrough, defuddle:static, defuddle:static-bot, defuddle:playwright, gemini
  - `duration_ms` — wall time
  - `data.chars`, `data.images`, `data.pages` — output stats
- `document_extraction_error` — extraction failed
  - `processor_slug`, `data.error`, `data.content_type`
- `extraction_estimate` — pre-check token estimate
- `page_extraction_complete`, `page_extraction_error` — per-page Gemini API calls (incl. token counts)

**API rate limits:**
- `api_rate_limit` — emitted on every 429 response from external APIs before retry
  - `data.api_name` — which API (e.g. "gemini")
  - `status_code` — always 429
  - `retry_count` — 0-indexed attempt number when the 429 occurred
  - Any occurrence means we're hitting rate limits. Occasional is expected under load; sustained = need to throttle or increase quota.

**Gateway-internal errors and warnings:**
- `error` — gateway-side failures caught by exception handlers (e.g., cache write failures, DB errors during result processing). These are NOT pipeline-specific errors — they indicate something broke inside the gateway itself. Check `data.message` for details.
- `warning` — non-fatal issues worth tracking (e.g., near-failures, degraded behavior)
- ANY `error` event is a red flag. These represent failures that may silently drop work — e.g., a synthesis result that completed but couldn't be cached, leaving the user with no audio.
- **`Background task <name> crashed` / `Background task <name> exited unexpectedly`** — a long-lived loop (billing-consumer, result-consumer, cache-persister, tts-visibility, yolo-visibility, batch-poller, cache-lru-flush, cache-maintenance, usage-log-cleanup, guest-cleanup, billing-sync, openai-tts-dispatcher, metrics-writer) is **gone** and is not coming back. Whatever that loop does has stopped silently for the rest of the process lifetime. **P0 — a gateway restart is required to recover.** Identify the loop from the name and report what has stopped (e.g. billing-consumer = nothing is being billed).
- **`Billing consumer group missing (Redis reset?), re-creating`** (WARNING, `yapit.gateway.billing_consumer`) — Redis was recreated and the consumer group was rebuilt automatically. One occurrence per Redis restart is expected and self-healing; nothing to do. A *repeating* pattern means Redis is restarting in a loop — investigate that instead.
- Stuck-loop retries back off exponentially (1s→60s), so a stuck loop produces roughly 1 error/minute. Judge such errors by the span between first and last occurrence — a low count can still be a dead loop.

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

**URL fetching (transport-level):**
- `url_fetch` — document URL downloads
  - `duration_ms`, `data.content_type`, `data.size_bytes` on success
  - `data.error` on failure (http_status or request_error)

## What to Analyze

### Fix check (before writing up any incident)

Match every incident against RECENT COMMITS first. An incident that an already-deployed commit fixes is not news — drop it from the report entirely: no issue, no pattern, no line in the summary, no bearing on the status line.

Judge the match on substance rather than on a plausible-looking subject line. `git show <sha>` gives the full message and diff, and the checked-out tree is the code that fix landed in — read both until you can name the failing path the commit changed. Two things break a match, and both are worth reporting: the commit is not in DEPLOYS yet (the bug is still live in prod — report it and say the fix is awaiting deploy), or the failure recurs after that deploy (the fix did not take — report that it did not).

Recovery is not a fix. An outage that ended, a background loop that came back after a restart, a queue that drained — with no commit behind it, nobody has addressed the cause, and it stays in the report as an issue.

### Metrics freshness
A STALE verdict in the METRICS FRESHNESS section is the lead issue of the report (P0): the metrics pipeline is down, and the metrics DB only covers the period before the gap — the window after it is unobserved, not quiet. Analyze that window from logs, and label each finding metrics-based or log-based.

The metrics writer self-heals: it buffers events (bounded, 10k) and retries with backoff when the metrics DB is unreachable. Log lines to know (module `yapit.gateway.metrics`):
- `Metrics DB unavailable at startup (...); writer will keep retrying` / `Metrics DB write failed (...); buffering events and retrying` (ERROR) — outage started
- `Metrics DB still unavailable after Xs (...)` (ERROR, repeated ~every 10 min while down) — ongoing outage
- `Metrics DB recovered after Xs; flushed N buffered events (M dropped)` (INFO) + a `warning` metrics event `Metrics DB outage recovered` — outage over; run the Fix check on it, and where it stays in the report, state the dropped events as a permanent gap
An outage-start ERROR with no matching recovery = the pipeline is down right now.

### Errors — HIGHEST PRIORITY
Read the actual error messages and investigate — a count alone is not analysis.

**Metrics DB errors:**
- `error` events (gateway-internal) — ANY nonzero count is a red flag. Read `data.message` for each. These represent silent failures that may cause user-visible breakage (e.g., audio not playing, results disappearing).
- `synthesis_error` events — worker-reported failures. Check `data.error` for each distinct error message.
- `detection_error`, `page_extraction_error` — same: read the actual error messages.
- `job_dlq` — ANY entry means something is systematically broken. Investigate immediately.
- `job_requeued` — occasional is fine (transient), sustained pattern = worker issues.

**Log file errors (data/logs/*.jsonl):**
- **Check the time range of gateway.jsonl first** (first and last entry timestamps). The file can span weeks. Start analysis with the last 24-48h — filter by `.record.time.repr > "YYYY-MM-DD"`. Total error counts across the whole file are misleading without date context. Older entries are useful for establishing baselines or investigating trends when something looks suspicious.
- Scan for ERROR and WARNING level entries within the recent window. Don't skip this even if metrics look clean — some errors only appear in logs.
- For each distinct error, report: the error message, count, and time range.
- ERROR level in logs — stack traces, exceptions (include request context: method, path, user_id, request_id)

### Warnings
- WARNING level in logs — library warnings, deprecations, near-failures
- How often do they occur? Any patterns by module or time?
- Warnings often precede errors — look for escalation patterns

### Queue Health
- `queue_depth` in `synthesis_queued`, `queue_wait_ms` in `synthesis_complete` — thresholds in the Normal vs Concerning table; sustained breaches = capacity issue

### Worker Performance
- `worker_latency_ms` per `worker_id` — compare workers, find outliers
- Throughput: count of completions per worker
- Error rate per worker — one worker failing more than others?

### Document Processing
- `document_extraction_complete` — volume by `processor_slug` (pymupdf, epub, passthrough, defuddle:*, gemini)
- `document_extraction_error` — any errors? Check `data.error` for each. Group by processor.
- Duration outliers per processor — compare against typical ranges

### Extraction (Gemini)
- `page_extraction_error` — rate limit (429), server errors (5xx)?
- Token counts — unusual spikes?
- **OCR token quota warnings** (`Usage limit exceeded for ocr_tokens`): These are **expected user-level quota enforcement**, NOT system errors. `limit 0` means the user has no AI extraction quota (all anonymous users, free-tier users who exhausted theirs). The extraction falls back to pymupdf (non-OCR). Do NOT flag these as issues or recommend checking the Google Cloud console — they are working as designed.
- **Batch poller 503s:** The Gemini batch GET endpoint intermittently returns 503 UNAVAILABLE (Google-side capacity issues, well-documented on their forums). The poller retries every 15s automatically. Only flag if a batch has been stuck for >24h — check time since `batch_job_submitted` event.

### Billing Health
See the BILLING RECONCILIATION section — event counts and character totals are pre-computed.
- **Event delta**: should be 0 for completed days. Non-zero on the current (partial) day is OK (in-flight). Non-zero on past days = lost billing events.
- **Consumer liveness**: flagged automatically if synthesis runs ahead of billing by >1h.
- **Character ratio** (billed/synth): varies by model mix (usage_multiplier per model). A sudden ratio shift without a model mix change = billing bug.
- billing_processed errors: any `error` events with billing context indicate billing consumer failures.

### Cache

- Vacuum runs as a background task in the gateway, checking every 24h. It only vacuums if `bloat_ratio` (file_size / data_size) exceeds 2.0x. **No vacuum events = bloat is under threshold = healthy.** This is not a missing cron. SQLite WAL mode with steady insert/delete keeps fragmentation low naturally.

### Cloudflare Edge (see CLOUDFLARE ANALYTICS section)
- **504 errors**: Check total count, origin response status, and affected hosts/IPs.
  - `origin_unreachable` (originResponseStatus=0) means CF couldn't reach origin — this is a CF/network issue, not an origin bug.
  - Non-zero originResponseStatus means origin responded with an error — investigate origin.
- **Cache hit ratio**: Low by design — most requests are unique text×voice×model. Hits only on shared/preview docs or replayed blocks. Ratio <1% would suggest the cache rule is broken.
- **5xx by hour**: Correlate spikes with deploy log times and metrics events.
- **Background 504 rate ~10-12%** is a known baseline (CF edge ↔ Hetzner transient path issues). Flag if significantly higher.

### Proxy Diagnostics (see PROXY DIAGNOSTICS section)
- **Stack Auth:** Response time distribution and status codes. Baseline (Mar 2026): p50 ~90ms, p99 ~600ms, all 200s. Watch for: non-200 status codes, p99 >2s sustained. Error lines: "S3 is not configured" and "Missing environment variable: STACK_VERCEL_SANDBOX_TOKEN" are known-benign (unused features). Only flag *new* error patterns.
- **Traefik:** Per-service latency breakdown. WebSocket connections (status 0) are excluded from latency stats. Note that Traefik logs upstream 5xx — a 500 on an API path is a gateway bug, while a 502 on any path means Traefik couldn't reach the upstream service. Slow static asset requests (JS/CSS) are usually slow client connections, not server issues.

## What's Normal vs Concerning

| Metric | Normal | Concerning |
|--------|--------|------------|
| `error` events | 0 | Any (investigate — read data.message) |
| DLQ entries | 0 | Any (investigate immediately) |
| Error rate (synthesis) | 0% | >0% sustained |
| Log ERROR entries | 0 | Any (read the actual messages) |
| Queue depth | <10 | >20 sustained |
| Queue wait (TTS) | <15s | >25s sustained |
| Queue wait (YOLO) | <5s | >8s sustained |
| Requeues | Rare/isolated | Pattern (same worker, same error) |
| Billing sync drift | 0 | Any (check which webhooks are being missed) |
| Billing reconciliation delta | 0 (past days) | Any non-zero on completed days |
| CF 504 rate | <15% | >20% or originResponseStatus != 0 |
| CF cache hit ratio | Low (unique content) | <1% sustained (cache rule broken) |
| Doc extraction errors | 0 | Any (check processor_slug + data.error) |

Events older than 3-7 days can be ignored unless part of a larger pattern / investigation.
E.g. items on the DLQ from >7 days ago are almost certainly already taken care of.

One-time short Redis blips coincide with deploys and are not worth flagging; flag them when their cadence exceeds deploy frequency or doesn't line up with deploy times.

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
- `queue_type`, `model_slug` — scanner logs
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

Open with the status line (no throat-clearing preamble):
- ✅ **All nominal** — no issues
- ⚠️ **Issues detected** — problems found
- 🔍 **Anomalies noted** — unusual patterns worth noting (no/low traffic is not an anomaly, unless there's a sudden change)

Then:
1. **Summary** (2-3 sentences)
2. **Key Metrics** (bullets: counts, rates, latencies)
3. **Issues** (if any — what, severity, details)
4. **Patterns** (correlations, clusters, trends)
5. **Recommendations** (if actionable)

Be concise but complete. This is a diagnostic report.

## Limitations

You have access to **synced static data** (metrics DB + logs up to sync time) and **the repository** at the current checkout — source and full git history, for the Fix check and for reading the code behind any failure.
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
- DO NOT use subagents.
EOF

echo "Running Claude analysis..."

run_analysis() {
    clankr run "$PROJECT_DIR" -p "$SCRIPT_DIR/report-profile" \
        -- --system-prompt "$PROMPT" \
        --output-format json \
        -p "$EXTRA_CONTEXT" \
        2>>"$REPORT_DIR/claude-stderr.log"
}

: > "$REPORT_DIR/claude-stderr.log"

output=""
for attempt in 1 2 3; do
    if output=$(run_analysis); then
        break
    fi
    output=""
    echo "Claude analysis failed (attempt ${attempt}/3)"
    if [[ "$attempt" -lt 3 ]]; then
        sleep $((attempt * 60))
    fi
done

if [[ -z "$output" ]]; then
    # A night the report could not run is recorded, not notified: one bad night
    # says nothing, and a run of them is what the overdue watchdog is for.
    echo "Claude analysis failed after 3 attempts. stderr:"
    cat "$REPORT_DIR/claude-stderr.log"
    fail_reason="the analysis agent failed three times — $(tail -c 200 "$REPORT_DIR/claude-stderr.log" | tr '\n' ' ')"
    exit 1
fi

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

status=$(printf '%s' "$result" | classify)

# Only a report that found issues is worth a notification. A green day and an
# anomaly note are read from the dashboard, on the reader's schedule. A report
# whose status line cannot be found still pings: unreadable is not the same as
# fine, and it may be an "issues detected" this could not see.
case "$status" in
    issues)  TITLE="⚠️ Yapit health: issues detected" ;;
    unknown) TITLE="🔍 Yapit health: could not tell how it went" ;;
    *)       TITLE="" ;;
esac

# Delivery happens before the run is recorded, so the record can say what
# became of it (stats.alert); a failed send never changes the run's own outcome.
alert=""
if [[ -z "$TITLE" ]]; then
    echo ""
    echo "Status: $status — recorded, no notification sent."
elif ! command -v alert-send >/dev/null 2>&1; then
    alert="delivery failed (alert-send not on PATH)"
    echo ""
    echo "Status: $status — alert-send is not on PATH, so nothing was notified." >&2
else
    echo ""
    echo "Status: $status — sending alert email..."
    if printf '%s' "$message" | alert-send "$TITLE"; then
        alert="delivered"
        echo "Alert sent."
    else
        alert="delivery failed (alert-send exited $?)"
        echo "Alert delivery failed — recorded in the run log." >&2
    fi
fi

log_run ok "" "$(jq -n --arg status "$status" --arg report "$REPORT_FILE" \
    --arg session "$session_id" --arg alert "$alert" \
    '{status: $status, report: $report, session: $session, alert: $alert}
     | if .alert == "" then del(.alert) else . end')"
