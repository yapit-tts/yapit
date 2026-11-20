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
# The timer runs this weekly, so the edge and proxy sections cover the week since
# the last run; a post-deploy report looks at the last day.
WINDOW_HOURS=168
while [[ $# -gt 0 ]]; do
    case $1 in
        --after-deploy) AFTER_DEPLOY=true; WINDOW_HOURS=24; shift ;;
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
CF_REPORT=$(uv run "$SCRIPT_DIR/cf_analytics.py" --plain --hours "$WINDOW_HOURS" 2>&1 || echo "(cf_analytics.py failed — is CLOUDFLARE_API_TOKEN set?)")

# Capture proxy diagnostics (Traefik from VPS container logs)
echo "Gathering proxy diagnostics..."
PROXY_REPORT=$(uv run "$SCRIPT_DIR/proxy_diagnostics.py" --hours "$WINDOW_HOURS" 2>&1 || echo "(proxy_diagnostics.py failed — is VPS_HOST set and SSH working?)")

# Billing reconciliation (synthesis events vs billing events)
echo "Running billing reconciliation..."
BILLING_RECON=$(uv run "$SCRIPT_DIR/billing_reconciliation.py" --days 14 2>&1 || echo "(billing_reconciliation.py failed)")

# Recent commits + deploys, so incidents can be checked against the fix that landed after them
GIT_LOG=$(git log -30 --date=format-local:'%Y-%m-%d %H:%M' --format='%ad  %h  %s')
DEPLOY_LOG=$(tail -10 "$PROJECT_DIR/.deploys.log" 2>/dev/null || echo "(no deploy log)")

# The task line goes last, after the data it is about
if $AFTER_DEPLOY; then
    TASK="This run follows a deploy. Report what changed since it: new errors, and anything that behaves differently than before."
else
    TASK="This is the weekly health check. Report on the last 7 days."
fi

EXTRA_CONTEXT="## METRICS FRESHNESS (newest metrics event vs the writer's heartbeat interval, pre-computed)

$METRICS_FRESHNESS

## DISK_USAGE (current snapshot)

$DISK_REPORT

## DISK_HISTORY (last 50 entries)

$DISK_HISTORY

## CLOUDFLARE ANALYTICS (edge traffic, cache, errors, 504 diagnostics)

$CF_REPORT

## PROXY DIAGNOSTICS (Traefik from VPS container logs)

$PROXY_REPORT

## BILLING RECONCILIATION (synthesis events vs billing events, pre-computed)

$BILLING_RECON

## RECENT COMMITS (last 30, newest first, local time)

$GIT_LOG

## DEPLOYS (last 10, local time — when a commit reached prod; FAILED = deploy aborted, code did not ship)

$DEPLOY_LOG

---

$TASK"

# The analysis prompt
read -r -d '' PROMPT << 'EOF' || true
You are the health check for Yapit TTS, a text-to-speech platform in production. The message holds data collected from production just before this run, and the metrics database and logs are synced into this checkout. Your final message is the report: a person reads it on its own to decide whether anything needs doing, and the run ends with it. Do the whole analysis in this run and write the report last.

The window is the 7 days before the newest log entry, or the time since the deploy when the message says this run follows one. Older data is the baseline for what normal looks like.

## Tools

- **Metrics:** `duckdb -readonly -safe data/metrics.duckdb "<SQL>"`. This exact prefix is the only form in which Bash runs DuckDB. Start with `DESCRIBE metrics_event`.
- **Logs:** `data/logs/*.jsonl`, searched with Grep and read with Read.
- **Code and history:** Read and Grep over this checkout, `git log` and `git show`.

Bash runs one plain command per call, starting with the command's name, and refuses anything else. You work from synced data, so live Redis queues and live worker state are out of reach.

## System

- **TTS:** users submit text blocks. Jobs go to one Redis queue per model (`tts:queue:kokoro`), TTS workers synthesize them and push results, and the gateway consumes the results and streams audio to clients over WebSocket. Models: `kokoro` (local) and `openai-tts` (not configured in production).
- **Detection:** PDF pages are rendered to images, YOLO workers find figures in them, and the results feed Gemini extraction.
- **Reliability:** a job a worker holds past its visibility timeout (TTS 20 s, YOLO 10 s) is requeued. A job that exhausts its retries goes to the dead letter queue (DLQ), which means something is systematically broken.
- **Background loops** in the gateway: billing-consumer, result-consumer, cache-persister, tts-visibility, yolo-visibility, batch-poller, cache-lru-flush, cache-maintenance, usage-log-cleanup, guest-cleanup, billing-sync, openai-tts-dispatcher, metrics-writer.
- **Cache caps** in production: audio 30 GB, extraction 30 GB, document 5 GB.

## Data

**Metrics** (`data/metrics.duckdb`, timestamps in CET). `metrics_event` holds raw events for 30 days; `metrics_hourly` and `metrics_daily` are aggregates. Fields such as `queue_wait_ms`, `worker_latency_ms`, `worker_id`, `model_slug`, `processor_slug`, `duration_ms` and `status_code` are top-level columns; the `data` JSON column holds only the rest (`data->>'error'`).

Event types:
- `synthesis_queued` (`queue_depth`), `synthesis_complete` (`queue_wait_ms`, `worker_latency_ms`, `worker_id`), `synthesis_error`
- `detection_queued`, `detection_complete`, `detection_error`
- `job_requeued` (a visibility timeout fired), `job_dlq`
- `heartbeat`: written by the metrics writer whenever its interval passes with no other write. Leave it out of activity counts.
- `document_extraction_complete` (`processor_slug`: pymupdf, epub, passthrough, defuddle:static, defuddle:static-bot, defuddle:playwright, gemini; `duration_ms`; `data.chars`, `data.images`, `data.pages`) and `document_extraction_error` (`processor_slug`, `data.error`, `data.content_type`)
- `extraction_estimate`; `page_extraction_complete` and `page_extraction_error`, one per Gemini page call, with token counts
- `api_rate_limit`: every 429 from an external API, before the retry (`data.api_name`, `retry_count`)
- `error` and `warning`: failures and near-failures the gateway caught itself (`data.message`). An `error` can mean work was silently dropped, such as audio that was synthesized but never cached.
- `stripe_webhook` (`duration_ms`, `data.event_type`, `status_code` 500 when the handler crashed; Stripe gives up at 20 s), `billing_sync_drift` (a missed webhook: `data.user_id`, `data.drift`), `billing_processed` (`duration_ms`, `text_length`, `data.events_count`, `data.users_count`)
- `url_fetch` (`duration_ms`, `data.content_type`, `data.size_bytes`, or `data.error`)

**Logs** (`data/logs/*.jsonl`, timestamps in UTC). Loguru JSON, one record per line. `gateway.jsonl` is the newest file and can span weeks; rotated files carry their start time in the name. Each record has `record.level.name`, `record.name` (the module), `record.message`, `record.time.repr`, `record.exception`, and context in `record.extra`: `request_id` on HTTP requests, `user_id`, `job_id`, `variant_hash`, `model_slug` and `worker_id` on TTS jobs, `extraction_id` and `content_hash` on extractions, `document_id`, and `method` and `path` on unhandled exceptions. These ids follow one request, job or extraction across components. `user_id` `cache-warmer` is the job that pre-synthesizes voice previews.

## What to check

Work through these in order. Every distinct error message in the window ends up in the report: as an issue, as a pattern, as matched to a fix, or as a known pattern.

1. **Metrics freshness.** The METRICS FRESHNESS verdict is deterministic and stands as given. STALE leads the report as a P0: the metrics pipeline is down, and the time after the gap is unobserved, not quiet. Analyse that time from the logs, and label each finding metrics-based or log-based. In the logs (module `yapit.gateway.metrics`), `Metrics DB unavailable at startup` or `Metrics DB write failed` starts an outage, `Metrics DB still unavailable after Xs` repeats while it lasts, and `Metrics DB recovered after Xs; flushed N buffered events (M dropped)` ends it; the M dropped events are a permanent gap. A start with no recovery means the pipeline is down now.
2. **Errors.** From the metrics: each `error`, `synthesis_error`, `detection_error`, `document_extraction_error`, `page_extraction_error` and `job_dlq`. From the logs: each ERROR and WARNING. For each distinct message, give what it says, its count, its first and last time, and its request context, and read the code path behind it.
   - `Background task <name> crashed` or `Background task <name> exited unexpectedly`: that loop is gone until the gateway restarts. It is a P0; say what has stopped (billing-consumer gone means nothing is billed).
   - A stuck loop backs off from 1 s to 60 s, so it logs about one error a minute. Judge it by the span from first to last occurrence, since a low count can still be a dead loop.
   - A `page_extraction_error` with status 402 (`RESOURCE_EXHAUSTED`, "prepayment credits are depleted"): the Gemini prepay balance is empty, and every AI Transform upload fails until someone buys credits in AI Studio. A P0 while it lasts; give when it started and whether a later successful Gemini page shows it ended.
   - `Auth email to an address at <domain> failed`: someone could not sign in by email or confirm an email change. Always an issue; the exception says whether SMTP rejected the credentials, the recipient or the connection.
   - Warnings that climb toward errors are a pattern to report.
3. **Queues and workers.** Queue depth and wait against the thresholds below. Latency, throughput and error rate per `worker_id`, and any outlier among them. Requeues that cluster on one worker or one error.
4. **Documents and extraction.** Volume and errors per `processor_slug`, and duration outliers per processor. Gemini 429s, 5xx responses and token spikes.
5. **Billing.** BILLING RECONCILIATION is pre-computed. A non-zero delta on a completed day is lost billing events; today's partial day may still be in flight. A liveness flag means billing fell more than an hour behind synthesis. A shift in the billed-to-synthesized character ratio with no change in model mix is a billing bug. Also check `stripe_webhook` latency and 500s, and any `billing_sync_drift`.
6. **Edge and proxy.** In CLOUDFLARE ANALYTICS, a 504 with `originResponseStatus` 0 (origin_unreachable) is the Cloudflare-to-Hetzner path; a non-zero origin status is the origin failing. Line up 5xx hours with DEPLOYS and the gateway logs. In PROXY DIAGNOSTICS, slow and 5xx lines carry UTC times on the gateway log's clock. A 500 on an API path is a gateway bug; a 502 is Traefik failing to reach the service.
7. **Disk.** Growth in DISK_USAGE and DISK_HISTORY, against the cache caps.

## Fix check

Before writing up an incident, match it against RECENT COMMITS. An incident that a deployed commit fixes is not news: leave it out of the report entirely, including the summary and the status line.

Judge the match on substance. `git show <sha>` gives the full message and diff, and this checkout is the code the fix landed in: read both until you can name the failing path the commit changed. Two things break a match, and both belong in the report: the commit is not in DEPLOYS yet (the bug is still live; say the fix awaits deploy), or the failure recurs after that deploy (the fix did not take).

Recovery is not a fix. An outage that ended, a loop that came back after a restart, or a queue that drained, with no commit behind it, stays in the report as an issue.

## Known patterns

These are expected, and become issues only when they change shape:
- `Usage limit exceeded for ocr_tokens`: user quota enforcement. `limit 0` is any anonymous user or a free user who used theirs up, and extraction falls back to pymupdf.
- Gemini batch poller 503 UNAVAILABLE: Google-side capacity. The poller retries every 15 s. It is an issue once a batch has waited over 24 h since its `batch_job_submitted` event.
- No vacuum events: the gateway vacuums the SQLite cache only past 2.0× bloat, checked daily, so none means it is under that.
- `Billing consumer group missing (Redis reset?), re-creating`: once per Redis restart, and self-healing. A run of them means Redis restarts in a loop.
- Short Redis blips at deploy times. They matter when they come more often than deploys, or away from deploy times.
- Cloudflare 504s on about 10–12% of requests, all origin_unreachable.
- A low cache hit ratio: most requests are unique text × voice × model.
- Slow static assets (JS, CSS) in Traefik: slow client connections.
- Little or no traffic, unless it changed suddenly.

## Thresholds

| Metric | Normal | Concerning |
|--------|--------|------------|
| Synthesis error rate | 0% | >0% sustained |
| Queue depth | <10 | >20 sustained |
| Queue wait, TTS | <15 s | >25 s sustained |
| Queue wait, YOLO | <5 s | >8 s sustained |
| Requeues | rare, isolated | a pattern (same worker, same error) |
| Cloudflare 504 rate | <15% | >20%, or any non-zero origin status |
| Cloudflare cache hit ratio | low | <1% sustained (the cache rule is broken) |

## Report

The first line is exactly one of these status lines, which a script reads to decide whether to notify:
- ✅ **All nominal** — no issues
- ⚠️ **Issues detected** — problems that need someone
- 🔍 **Anomalies noted** — something unusual, nothing to act on yet

Then, with times in CET:
1. **Summary**: 2–3 sentences.
2. **Key metrics**: counts, rates and latencies for the window.
3. **Issues**: what, severity (P0 to P3), and the evidence.
4. **Patterns**: correlations, clusters, trends.
5. **Recommendations**, where something is actionable.
6. **Tooling gaps**: commands that were refused, and data, fields or a reusable query that would have made this analysis better within this offline setup. Leave the section out when there are none.
EOF

echo "Running Claude analysis..."

# The agent runs on this machine, so its reach is set here. --restricted keeps
# Read, Grep and Glob inside this checkout and refuses every write; .env holds
# prod secrets and is denied. Bash runs only the commands allowed below, and
# DuckDB's -safe mode shuts it out of every file but the database, of the
# environment and of extensions. Every run is logged by model-runs.
run_analysis() {
    CLAUDECODE= model-runs run --site yapit-health-report --timeout 1800 --json -- \
        claude -p --model opus --effort high --system-prompt "$PROMPT" \
        --setting-sources "" --strict-mcp-config --disable-slash-commands \
        --settings '{"autoMemoryEnabled": false}' --restricted \
        --tools "Read,Grep,Glob,Bash" \
        --allowedTools "Bash(duckdb -readonly -safe data/metrics.duckdb *)" \
            "Bash(git log)" "Bash(git log *)" "Bash(git show *)" \
        --disallowedTools "Read(./.env*)" "Bash(git *--output*)" \
        --permission-mode manual --permission-prompts none \
        <<<"$EXTRA_CONTEXT" 2>>"$REPORT_DIR/claude-stderr.log"
}

# The agent's commands inherit this environment, so .env's secrets leave it first.
if [[ -f "$PROJECT_DIR/.env" ]]; then
    unset $(sed -n 's/^\(export \)\{0,1\}\([A-Za-z_][A-Za-z0-9_]*\)=.*/\2/p' "$PROJECT_DIR/.env")
fi

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
    # A run the report could not finish is recorded, not notified: one bad run
    # says nothing, and a run of them is what the overdue watchdog is for.
    echo "Claude analysis failed after 3 attempts. stderr:"
    cat "$REPORT_DIR/claude-stderr.log"
    fail_reason="the analysis agent failed three times — $(tail -c 200 "$REPORT_DIR/claude-stderr.log" | tr '\n' ' ')"
    exit 1
fi

# model-runs --json prints claude's result object
result_event=$(echo "$output" | jq -c 'select(.type == "result")' 2>/dev/null || echo '{}')
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
