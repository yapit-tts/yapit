---
status: active
started: 2026-01-23
---

# Task: Stress Testing

Extracted from [[2026-01-13-monitoring-alerting]].

## Intent

Stress test the production TTS and YOLO pipelines to:
- Measure TTFA (time-to-first-audio), buffering, overflow behavior
- Compare before/after VPS tier upgrades
- Validate config constants (overflow thresholds, timeouts)
- Establish baseline: "X users at 2x → Y% underruns, Z ms TTFA p50/p95"

## Subtasks

- [[2026-02-11-overflow-tuning-jemalloc-worker-memory]] — Overflow timer tuning, jemalloc, oneDNN evaluation

## Sources

**Knowledge files:**
- [[tts-flow]] — Pipeline architecture, overflow mechanism
- [[infrastructure]] — Scripts section documents stress_test module
- [[metrics]] — Event types for post-hoc analysis

**Key code files:**
- `scripts/stress_test.py` — TTS stress test script
- `scripts/stress_test_yolo.py` — YOLO stress test script
- `yapit/gateway/__init__.py:49-56` — Overflow/visibility timeout constants
- `frontend/src/lib/playbackEngine.ts:36-39` — Frontend buffering constants (BATCH_SIZE, REFILL_THRESHOLD, MIN_BUFFER_TO_START)

## Usage

**Prerequisites:**
1. Create test user in prod UI
2. Give unlimited credits via DB: `UPDATE user_subscription SET server_kokoro_characters = NULL WHERE user_id = '...'`
3. Get auth token from browser dev tools (Application > Cookies > access_token)

**TTS stress test:**
```bash
uv run scripts/stress_test.py \
  --base-url https://yapit.md \
  --token TOKEN \
  --users 10 \
  --blocks 30 \
  --speed 2

# Test with cached content (no credits needed):
uv run scripts/stress_test.py --token TOKEN --users 1 --blocks 3 --use-cached
```

**YOLO overflow test:**
```bash
uv run scripts/stress_test_yolo.py \
  --base-url https://yapit.md \
  --token TOKEN \
  --pages 300 \
  --concurrent 2
```

Results saved to `scripts/stress_test/results/` as timestamped JSON.

## Done When

- [ ] Run stress test against prod successfully
- [ ] Establish baseline metrics before VPS upgrade
- [ ] Run again after VPS upgrade, compare results
- [ ] Validate overflow triggers as expected under load

## Discussion

### 2026-02-03

Implemented `scripts/stress_test/` module:
- Realistic playback simulation matching frontend prefetch algorithm
- Captures per-block arrival times for post-hoc TTFA calculation
- TTFA = time until 2nd block arrives (MIN_BUFFER_TO_START = 2)
- Speed multiplier adjusts simulated playback duration
- YOLO test generates synthetic PDFs on-the-fly via reportlab

Auth approach: Single test user with unlimited credits (DB manipulation), no need to disable BILLING_ENABLED system-wide. The 300 req/min rate limit per user is sufficient for triggering overflow.
