---
status: active
started: 2026-02-05
---

# Task: Stress test script fixes and improvements

Depends on [[2026-02-05-pubsub-per-document-channels]] — the cross-talk fix must land first, otherwise multi-user results remain invalid.

## Intent

The stress test script (`scripts/stress_test.py`) has several bugs and missing features that prevent it from producing reliable, analyzable results. Fix these so we can run `--users 20 --blocks 30` and get trustworthy data for tuning pipeline constants and comparing VPS tiers.

## Sources

**Knowledge files:**
- [[tts-flow]] — Pipeline architecture, worker model, overflow mechanism
- [[infrastructure]] — Scripts section

**Key code files:**
- MUST READ: `scripts/stress_test.py` — The entire script. ~510 lines. Read fully before editing.
- MUST READ: `scripts/stress_test_yolo.py` — YOLO variant, similar patterns.
- Reference: `yapit/gateway/api/v1/ws.py` — WebSocket handler, message types, error responses
- Reference: `yapit/gateway/seed.py` — Model/voice seed data (for default voice per model)
- Reference: `frontend/src/lib/playbackEngine.ts:36-39` — Frontend constants to match
- Reference: `yapit/gateway/__init__.py:162-175` — Inworld dispatcher setup (model slugs)

**Existing results (all multi-user ones invalid due to cross-talk):**
- `scripts/stress_test_results/` — 7 JSON files from 2026-02-04. Single-user results (1 user) are valid. Multi-user results are not.

## Bugs to fix

### 1. Server-level errors silently swallowed

`handle_messages` appends `type: "error"` messages to `session.errors` but doesn't fail pending blocks or abort. If the server rejects the request (wrong model/voice, rate limit), the script hangs forever waiting for blocks that were never queued.

**Fix:** On `type: "error"`, fail ALL pending blocks for this session and set `ws_dead = True` (or a similar abort flag). The session should terminate with errors captured.

### 2. Default voice should be per-model, not hardcoded

`--voice` defaults to `af_heart` (Kokoro). Using `--model inworld-1.5` with this default causes immediate server error (voice not found for model). The user shouldn't need to know voice slugs for stress testing.

**Fix:** Remove `--voice` parameter. Map model → default voice internally:
- `kokoro` → `af_heart`
- `inworld-1.5` → first voice from seed data or a known default
- `inworld-1.5-max` → same

### 3. `--use-cached` stalls at ~80% (16/20 blocks)

With cached blocks returning instantly, the refill logic has a timing race. Blocks 0-15 (2 batches of 8) arrive instantly. The third batch (16-19) depends on playback advancing far enough to trigger the refill threshold check, but the event loop scheduling creates a race between `asyncio.sleep` (playback) and the buffer check.

**Fix:** Investigate the refill logic flow with instant responses. Likely the `buffer_ahead` calculation or the refill trigger condition needs adjustment for the case where all blocks in a batch arrive simultaneously (no I/O wait to yield the event loop).

### 4. document_id filtering in status messages

Even after the server-side pubsub fix ([[2026-02-05-pubsub-per-document-channels]]), the script should still validate `document_id` in received status messages as defense-in-depth. It's one line and prevents future regressions.

## Improvements

### 5. Summary table enhancements

Add to `print_summary`:
- **Total wall time** — `finished_at - started_at`
- **Success fraction** — `completed/total` (e.g., "190/200 blocks")
- **Total underrun duration** — sum of all `waited_ms` across all sessions, per-user average
- **Per-block synthesis time p50/p95** — inter-arrival time between consecutive blocks (excluding batch boundary gaps, which are prefetch artifacts not synthesis delays)

### 6. Staggered start option

Add `--stagger SECONDS` (default 0). Spread user session starts over the specified window:
```python
await asyncio.sleep(i * stagger_seconds)
```
Useful for more realistic load patterns (users don't all press play simultaneously). The lockstep start (`asyncio.gather` with all tasks) is a worst-case burst scenario — useful but not the only scenario worth testing.

### 7. YOLO script: add auth from env file

`stress_test_yolo.py` still requires `--token` manually. Port the same env-file auth logic from `stress_test.py` (read `TEST_EMAIL`/`TEST_PASSWORD` from `.env`, auto-fetch token via Stack Auth).

## Done When

- [ ] Running `--users 20 --blocks 30` completes and produces valid per-user timing data
- [ ] Running with `--model inworld-1.5` either works or fails fast with a clear error
- [ ] Running with `--use-cached` completes all blocks
- [ ] Server-level errors cause immediate session abort with captured error messages
- [ ] Summary table shows wall time, success fraction, underrun totals
- [ ] All existing multi-user results re-run after fixes to establish valid baselines
