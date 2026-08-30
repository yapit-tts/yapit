#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPORT_DIR="$HOME/logs/yapit-reports"
mkdir -p "$REPORT_DIR"

UNIT=yapit-dep-scout

# How far into a report the status line may sit. The scout is asked for it on the
# first line; the saved file puts a session header in front of that, and an agent
# sometimes puts a sentence there too.
HEAD_LINES=20

# The line the report opens with, where it says whether it found something needing
# a person. `scripts/dep-scout-profile/CLAUDE.md` defines it and is the only place
# that does. Reads all of its input after finding it, so that whatever is writing
# to this never takes a SIGPIPE mid-report — a report long enough to fill a pipe
# would otherwise kill the run between saving itself and notifying.
status_line() {  # report text on stdin -> that line, empty if it has none
    local line found="" n=0
    # `|| [[ -n "$line" ]]` so a report whose last line has no newline after it —
    # which is how the agent's result arrives — is still read.
    while IFS= read -r line || [[ -n "$line" ]]; do
        n=$((n + 1))
        if [[ -z "$found" && "$n" -le "$HEAD_LINES" ]]; then
            case "$line" in
                *⚠*|*✅*) found="$line" ;;
            esac
        fi
    done
    printf '%s' "$found"
}

classify() {  # report text on stdin -> actionable|routine|unknown
    case "$(status_line)" in
        *⚠*) echo actionable ;;
        *✅*) echo routine ;;
        *)   echo unknown ;;
    esac
}

# The status line as a notification title: what was found, without the markers and
# the label in front of it.
headline() {  # status line -> the clause naming the finding, empty if there is none
    local text
    text=$(printf '%s' "$1" | sed -e 's/⚠️//g' -e 's/⚠//g' -e 's/✅//g' -e 's/[*`#]//g' \
        -e 's/^[[:space:]]*//' -e 's/^Action required//' -e 's/^Nothing to act on//' \
        -e 's/^[[:space:]—-]*//' -e 's/[[:space:]]*$//')
    if [[ "${#text}" -gt 110 ]]; then
        text="${text:0:110}"
        text="${text% *}…"
    fi
    printf '%s' "$text"
}

# What this run did, for anyone reading later: run-log keeps one line per run in
# ~/logs/runs/$UNIT.jsonl. Most runs notify nobody — a report with nothing to act
# on is read from the yapit dashboard, on whatever day there is time for it — so
# that line and the overdue watchdog behind it are what say the scout still runs.
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

while [[ $# -gt 0 ]]; do
    case $1 in
        --classify) classify; exit 0 ;;
        -h|--help)
            echo "Usage: $0 [--classify]"
            echo "  --classify  Read a report on stdin, print the verdict that decides whether it notifies"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

fail_reason=""
finish() {
    local rc=$?
    [[ "$rc" -eq 0 ]] && return 0
    log_run fail "${fail_reason:-dep-scout.sh exited $rc before finishing — journalctl --user -u $UNIT}"
}
trap finish EXIT

# These win over anything already exported.
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

echo "Gathering current dependency versions..."

# --- Python (main project) ---
PYTHON_DEPS=$(uv run python -c "
import tomllib, json
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
deps = data['project']['dependencies']
print(json.dumps(deps, indent=2))
")

# --- Frontend (npm) ---
FRONTEND_DEPS=$(uv run python -c "
import json
with open('frontend/package.json') as f:
    data = json.load(f)
print(json.dumps({
    'dependencies': data.get('dependencies', {}),
    'devDependencies': data.get('devDependencies', {}),
    'overrides': data.get('overrides', {}),
}, indent=2))
")

# --- Defuddle service (npm) ---
DEFUDDLE_DEPS=$(uv run python -c "
import json
with open('docker/defuddle/package.json') as f:
    data = json.load(f)
print(json.dumps({
    'dependencies': data.get('dependencies', {}),
}, indent=2))
")

# --- npm audit ---
echo "Running npm audit..."
FRONTEND_AUDIT=$(cd frontend && npm audit --json 2>/dev/null || true)
DEFUDDLE_AUDIT=$(cd docker/defuddle && npm audit --json 2>/dev/null || true)

# --- Docker base images ---
DOCKER_IMAGES=$(grep -rh '^FROM ' docker/ yapit/ frontend/Dockerfile 2>/dev/null | sort -u)

# --- Stack Auth: pinned SHA and recent upstream commits ---
STACKAUTH_SHA=$(grep '^FROM stackauth/server:' docker/Dockerfile.stackauth | cut -d: -f2)
echo "Stack Auth pinned at: $STACKAUTH_SHA"
echo "Fetching Stack Auth commit log..."
STACKAUTH_COMMITS=$(gh api -X GET "repos/stack-auth/stack-auth/commits?per_page=30" \
    --jq '.[] | "- \(.sha[0:7]) \(.commit.message | split("\n")[0])"' 2>/dev/null || echo "(failed to fetch)")

# --- Latest PyPI versions ---
echo "Checking latest PyPI versions..."
PYPI_VERSIONS=$(uv run python -c "
import urllib.request, json, re

specs = json.loads('''$PYTHON_DEPS''')
seen = set()
results = {}
for spec in specs:
    name = re.split(r'[~>=<!\[]', spec)[0].strip().lower()
    if name in seen:
        continue
    seen.add(name)
    try:
        url = f'https://pypi.org/pypi/{name}/json'
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            results[name] = data['info']['version']
    except Exception:
        pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

# --- Latest npm versions ---
echo "Checking latest npm versions..."
FRONTEND_LATEST=$(uv run python -c "
import subprocess, json

results = {}
for pkg_file in ['frontend/package.json', 'docker/defuddle/package.json']:
    with open(pkg_file) as f:
        data = json.load(f)
    for section in ['dependencies', 'devDependencies']:
        for pkg in data.get(section, {}):
            if pkg in results:
                continue
            try:
                out = subprocess.run(
                    ['npm', 'view', pkg, 'version'],
                    capture_output=True, text=True, timeout=10
                )
                ver = out.stdout.strip()
                if ver:
                    results[pkg] = ver
            except Exception:
                pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

# --- Build the data payload ---
DATA="## Current Dependency Inventory

### Python — main project (pyproject.toml)
$PYTHON_DEPS

### Frontend (frontend/package.json)
$FRONTEND_DEPS

### Defuddle service (docker/defuddle/package.json)
$DEFUDDLE_DEPS

### npm audit — frontend
$FRONTEND_AUDIT

### npm audit — defuddle
$DEFUDDLE_AUDIT

### Docker base images
$DOCKER_IMAGES

### Stack Auth
Pinned SHA: $STACKAUTH_SHA
Recent upstream commits (newest first):
$STACKAUTH_COMMITS

### Latest available versions (PyPI)
$PYPI_VERSIONS

### Latest available versions (npm)
$FRONTEND_LATEST"

echo "Running Claude analysis..."
output=$(clankr run "$PROJECT_DIR" -p "$SCRIPT_DIR/dep-scout-profile" \
    -- -p "$DATA" \
    --allowedTools "WebSearch,WebFetch" \
    --output-format json \
    2>"$REPORT_DIR/dep-scout-stderr.log") || {
    echo "Claude analysis failed. stderr:"
    cat "$REPORT_DIR/dep-scout-stderr.log"
    echo "stdout: $output"
    fail_reason="the analysis agent failed — $(tail -c 200 "$REPORT_DIR/dep-scout-stderr.log" | tr '\n' ' ')"
    exit 1
}

result_event=$(echo "$output" | jq -c '.[] | select(.type == "result")' 2>/dev/null || echo "$output" | jq -c 'select(.type == "result")' 2>/dev/null || echo '{}')
session_id=$(echo "$result_event" | jq -r '.session_id // "unknown"')
result=$(echo "$result_event" | jq -r '.result // "No result"')

message="Dep Scout — Session: $session_id
---

$result"

# Save report
REPORT_FILE="$REPORT_DIR/dep-scout-$(date +%Y-%m-%d).md"
echo "$message" > "$REPORT_FILE"
echo "Report saved to: $REPORT_FILE"
echo ""
echo "$message"

line=$(printf '%s' "$result" | status_line)
status=$(printf '%s' "$line" | classify)

# A scout report that found something to patch or migrate is worth interrupting
# someone for; one that found only hygiene is read from the dashboard, on the
# reader's schedule. A report whose status line cannot be found still pings:
# unreadable is not the same as nothing to do.
naming=$(headline "$line")
case "$status" in
    actionable) TITLE="⚠️ Yapit deps: ${naming:-action required}" ;;
    unknown)    TITLE="🔍 Yapit deps: could not tell whether it found anything" ;;
    *)          TITLE="" ;;
esac

# Delivery happens before the run is recorded, so the record can say what
# became of it: a failed send must be readable somewhere that is not the
# channel that just failed, and must not change the run's own outcome.
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
