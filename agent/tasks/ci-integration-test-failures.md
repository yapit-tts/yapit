---
status: done
created: 2026-01-05
completed: 2026-01-05
---

78d1714ea0045be01a2550d001e798c7f6423cc3

# CI Integration Test Failures - Kokoro TTS Timeouts

## Problem
Integration tests fail in CI but pass locally. The kokoro worker becomes unresponsive after ~8 successful synthesis requests, causing all subsequent requests to timeout.

## Symptoms
- First 8 synthesis requests succeed (~7s each)
- Then ALL requests suddenly timeout at once (60s httpx timeout)
- No errors or logs from kokoro worker - just silence
- Container stays "healthy" but unresponsive

## Environment Differences
- **CI**: 2 vCPU, 7.7GB RAM (ubuntu-latest)
- **Local**: More resources, works fine

## Changes Made (to keep)

### Committed fixes for other CI issues
- `tts_processors.ci.json` - minimal processor config without Inworld
- `dev-ci` make target - no stripe profile
- `KOKORO_CPU_REPLICAS=1` in CI
- Health check for kokoro-cpu container
- `OMP_NUM_THREADS` configurable via docker-compose (CI sets to 2)
- Show container logs on test failure (moved after test step)
- Added `websockets` to test dependencies

### Debugging changes (may revert)
- Increased httpx timeout to 180s
- Added logging to kokoro worker

## Investigation Findings

1. **Thread contention hypothesis** - Tried `OMP_NUM_THREADS=2` instead of 4. Still fails.

2. **Blocking call in async** - `synthesize()` uses asyncio.Lock but the actual `self._pipe()` call is blocking. If it hangs, event loop freezes.

3. **No worker logs** - uvicorn doesn't log requests by default, and no errors are captured when it hangs.

4. **Timing pattern**:
   - 00:43:18-00:44:06: Successful requests
   - 00:44:11: First timeout (60s after ~00:43:11 request)
   - Worker simply stops responding

## Current Status (2026-01-05)
- PR #52: https://github.com/yapit-tts/yapit/pull/52
- Branch: `fix/ci-kokoro-debug`
- Latest run: https://github.com/yapit-tts/yapit/actions/runs/20702558760

**Latest failure**: `container yapit-gateway-1 is unhealthy`
- stack-auth now healthy after increasing start_period to 180s
- Gateway is now the slow one

## Next Steps
- [ ] Increase gateway health check timeouts (currently 80s start_period)
- [ ] Check gateway logs via `gh run view <id> --log-failed`
- [ ] Worker logging added - check if requests are received
- [ ] httpx timeout increased to 180s - see if it helps with kokoro timeouts

## Possible Root Causes (unconfirmed)
- Memory pressure causing model to hang
- espeak-ng or torch deadlock
- Something in kokoro library on resource-constrained systems
- asyncio event loop starvation
