#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

REPORT_DIR="$HOME/tmp/yapit-reports"
mkdir -p "$REPORT_DIR"

# Load env vars (.env has NTFY_TOPIC, etc.)
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

# --- Python (defuddle service) ---
DEFUDDLE_DEPS=$(uv run python -c "
import tomllib, json
with open('docker/defuddle/pyproject.toml', 'rb') as f:
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

# --- Docker base images ---
DOCKER_IMAGES=$(grep -rh '^FROM ' docker/ yapit/ frontend/Dockerfile 2>/dev/null | sort -u)

# --- Stack Auth: pinned SHA and recent upstream commits ---
STACKAUTH_SHA=$(grep '^FROM stackauth/server:' docker/Dockerfile.stackauth | cut -d: -f2)
echo "Stack Auth pinned at: $STACKAUTH_SHA"
echo "Fetching Stack Auth commit log..."
STACKAUTH_COMMITS=$(gh api -X GET "repos/stack-auth/stack-auth/commits?per_page=30" \
    --jq '.[] | "- \(.sha[0:7]) \(.commit.message | split("\n")[0])"' 2>/dev/null || echo "(failed to fetch)")

# --- Latest PyPI versions (quick, deterministic) ---
echo "Checking latest PyPI versions..."
PYPI_VERSIONS=$(uv run python -c "
import subprocess, json, re

specs = json.loads('''$PYTHON_DEPS''') + json.loads('''$DEFUDDLE_DEPS''')
seen = set()
results = {}
for spec in specs:
    name = re.split(r'[~>=<!\[]', spec)[0].strip().lower()
    if name in seen:
        continue
    seen.add(name)
    try:
        out = subprocess.run(
            ['uv', 'pip', 'index', 'versions', name],
            capture_output=True, text=True, timeout=10
        )
        # Output: 'package (X.Y.Z)' on first line
        match = re.search(r'\(([^)]+)\)', out.stdout.split('\n')[0])
        if match:
            results[name] = match.group(1)
    except Exception:
        pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

# --- Latest npm versions ---
echo "Checking latest npm versions..."
FRONTEND_LATEST=$(uv run python -c "
import subprocess, json, re

with open('frontend/package.json') as f:
    data = json.load(f)

results = {}
for section in ['dependencies', 'devDependencies']:
    for pkg in data.get(section, {}):
        try:
            out = subprocess.run(
                ['npm', 'view', pkg, 'version'],
                capture_output=True, text=True, timeout=10,
                cwd='frontend'
            )
            ver = out.stdout.strip()
            if ver:
                results[pkg] = ver
        except Exception:
            pass
print(json.dumps(results, indent=2))
" 2>/dev/null)

ALLOWED_TOOLS="WebSearch,WebFetch"

CONTEXT="## Current Dependency Inventory

### Python — main project (pyproject.toml)
$PYTHON_DEPS

### Python — defuddle service (docker/defuddle/pyproject.toml)
$DEFUDDLE_DEPS

### Frontend (frontend/package.json)
$FRONTEND_DEPS

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

read -r -d '' PROMPT << 'PROMPT_EOF' || true
You are a dependency scout for Yapit TTS, an open-source text-to-speech platform.

Your job: analyze the dependency inventory below and produce an actionable update report.

## Instructions

1. Compare current pinned versions against the latest available versions provided.
2. For any dependency that is outdated, research what changed between current and latest:
   - Use WebSearch to find changelogs, release notes, or GitHub releases
   - Focus on: security fixes, performance improvements, new features, breaking changes
   - Be specific — "bug fixes" is not useful, "fixes memory leak in async context managers" is
   - **Cite your sources** — include a URL for every claim (changelog link, PR, CVE, release page)
3. Assess relevance to Yapit specifically:
   - HIGH: security fixes, performance wins in code paths we use, bug fixes we might hit
   - MEDIUM: useful new features, quality-of-life improvements
   - LOW: cosmetic changes, features we don't use, dev tooling minor bumps
   - SKIP: already current, or delta is trivial (patch bump with no meaningful changes)

## Special cases

**Playwright** — The bundled Chromium version is the real concern, not Playwright itself.
Check what Chromium version ships with the latest Playwright and whether there are
security fixes in the Chromium versions between our current and latest.

**Stack Auth** — No semver. Pinned by commit SHA. Check the commit log provided for:
migration files, env var changes, entrypoint changes, security-relevant commits.
Flag anything matching known gotchas: env var renames, Prisma version bumps,
ClickHouse schema changes, seed data changes.

**@stackframe/react** — Must be updated together with Stack Auth server. Note this
in the report if either is outdated.

**Docker base images** — Check if major/minor bumps are available (e.g. node:22 → node:24,
python:3.12 → 3.13, postgres:16 → 17). Only flag if there's a compelling reason to upgrade.

**Frontend deps** — Most are UI libraries with frequent patch releases. Only flag
if there are security fixes or breaking changes. Don't waste time on minor bumps
of radix-ui, lucide-react, etc. unless there's something notable.

## Output format

Start with a 2-3 sentence executive summary.

Then a table per ecosystem, sorted by relevance (HIGH first):

```
| Package | Current | Latest | What Changed | Relevance |
|---------|---------|--------|-------------|-----------|
```

After each table, list source URLs for the claims made (changelog links, PRs, CVEs).

Only include rows where the dependency is meaningfully outdated (skip patch bumps
with no notable changes). If an entire ecosystem has nothing notable, say so in
one line and skip the table.

End with a "Recommended actions" section — a short prioritized list of what's
actually worth updating, grouped by effort level (quick wins vs. involved updates).

Be concise. This is a scan, not a dissertation.
PROMPT_EOF

echo "Running Claude analysis..."
output=$(CLAUDE_CODE_SIMPLE=1 claude -p "$PROMPT" \
    --allowedTools "$ALLOWED_TOOLS" \
    --append-system-prompt "$CONTEXT" \
    --output-format json \
    2>"$REPORT_DIR/dep-scout-stderr.log") || {
    echo "Claude analysis failed. stderr: $(cat "$REPORT_DIR/dep-scout-stderr.log")"
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
        -H "Title: 📦 Yapit dependency report" \
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
