#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPORT_DIR="$HOME/tmp/yapit-reports"
mkdir -p "$REPORT_DIR"

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

# Send to ntfy
if [[ -n "${NTFY_TOPIC:-}" ]]; then
    echo ""
    echo "Sending to ntfy..."

    if [[ ${#message} -gt 3800 ]]; then
        ntfy_message="${message:0:3700}

... (truncated, full: $REPORT_FILE)"
    else
        ntfy_message="$message"
    fi

    printf '%s' "$ntfy_message" | curl -s \
        -H "Title: Yapit dependency report" \
        -H "Priority: low" \
        -H "Tags: dependencies" \
        -d @- \
        "https://ntfy.sh/${NTFY_TOPIC}" || {
        echo "ntfy notification failed (continuing anyway)"
    }
    echo "Sent to ntfy."
else
    echo "(NTFY_TOPIC not set, skipping ntfy)"
fi
