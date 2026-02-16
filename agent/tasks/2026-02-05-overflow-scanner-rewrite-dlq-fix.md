---
status: done
started: 2026-02-05
---

# Task: Overflow Scanner Rewrite + TTS DLQ Silent Failure

## Intent

The overflow scanner is the elastic escape valve — when local workers are overloaded, it offloads to RunPod serverless which has effectively infinite capacity. Currently the scanner bottlenecks this by processing one job at a time, blocking a thread for the full RunPod job duration (up to 60s). Separately, TTS jobs that exhaust retries and go to DLQ silently vanish — no error notification, no cleanup, block stuck in "processing" forever on the frontend.

Three issues to fix, all in the overflow/reliability path:

1. **Parallel overflow dispatch** — scanner currently picks one stale job, calls `run_sync` (blocks thread up to 60s), sleeps, repeat. Should submit all stale jobs at once and not hold threads for job duration.
2. **Overflow retry flow** — when RunPod fails (timeout, cold start, error), the job is permanently lost. Should re-queue into normal retry flow.
3. **TTS DLQ error notification** — when TTS jobs hit DLQ after max retries, no error result is pushed. YOLO handles this correctly; TTS doesn't.

## Assumptions

- RunPod serverless auto-scales; we should be able to submit hundreds of jobs without worrying about RunPod-side capacity limits.
- The RunPod SDK provides `AsyncioEndpoint` + `AsyncioJob` — native asyncio, no threads needed at all.
- Both TTS and YOLO overflow use the same `run_overflow_scanner` function — fix applies to both.
- `MAX_RETRIES = 3` — applies to all attempts (local worker + RunPod). An overflow failure counts as a failed attempt.

## Sources

**Knowledge files:**
- [[tts-flow]] — full TTS pipeline, worker architecture, reliability mechanisms
- [[infrastructure]] — worker services, overflow/visibility scanner overview

**External docs:**
- MUST READ: [RunPod Python SDK — Endpoints](https://docs.runpod.io/sdks/python/endpoints) — `AsyncioEndpoint`, `AsyncioJob`, `run()`, `status()`, `output()` API

**Key code files:**
- MUST READ: `yapit/gateway/overflow_scanner.py` — the file being rewritten
- MUST READ: `yapit/gateway/visibility_scanner.py` — reference for DLQ handling (YOLO does it right, TTS doesn't), and the retry/DLQ flow
- MUST READ: `yapit/gateway/result_consumer.py` — consumes results from `tts:results`, handles error path (inflight key cleanup, subscriber notification, metrics)
- MUST READ: `yapit/gateway/__init__.py` — where scanners are started, constants (thresholds, intervals, max_retries)
- Reference: `yapit/contracts.py` — `WorkerResult`, `SynthesisJob`, `TTS_RESULTS`, queue key patterns
- Reference: `yapit/workers/queue.py` — `requeue_job`, `move_to_dlq`
- Reference: `yapit/workers/handlers/runpod.py` — RunPod serverless handler (receives SynthesisJob, returns WorkerResult-compatible dict)

## Done When

- [ ] Overflow scanner submits all stale jobs to RunPod at once, not one at a time
- [ ] No threads blocked for job duration — only quick HTTP requests (submit, status poll)
- [ ] RunPod failures (timeout, error) re-queue the job into normal retry flow (retry count incremented)
- [ ] Jobs at max retries go to DLQ with proper error notification (not silently re-queued forever)
- [ ] TTS jobs hitting DLQ push a `WorkerResult` with error to `tts:results` so result_consumer cleans up (inflight key, subscribers, metrics)
- [ ] Works for both TTS and YOLO overflow (shared code)
- [ ] `make test-local` passes

## Design

### 1. Parallel overflow: submit + poll architecture

Replace sequential `run_sync` with `AsyncioEndpoint` + `AsyncioJob` (native asyncio, zero threads):

```python
# Setup (once at scanner start)
session = aiohttp.ClientSession()
endpoint = AsyncioEndpoint("ENDPOINT_ID", session)
```

```
Scan cycle (every 5s):
  1. Claim ALL stale jobs via zrangebyscore (age > threshold)
  2. Submit each to RunPod: job_handle = await endpoint.run(payload)
     - Add to outstanding list
     - Log job_overflow metric
  3. Poll ALL outstanding handles: status = await job_handle.status()
     - COMPLETED → output = await job_handle.output(), push result to Redis, log overflow_complete
     - FAILED/CANCELLED → handle as failure (see retry flow below)
     - Our timeout exceeded → handle as failure
     - Still pending → keep in outstanding
  4. Sleep scan_interval_s
```

`outstanding` list persists across scan cycles. New stale jobs are claimed every cycle even while prior jobs are processing on RunPod. All RunPod SDK calls are native async — no `to_thread`, no thread pool involvement.

### 2. Overflow retry flow

When RunPod fails (timeout, error, FAILED status):
- If `retry_count < max_retries`: call `requeue_job()` — job goes back into normal queue with incremented retry count. A local worker or another overflow attempt will pick it up.
- If `retry_count >= max_retries`: call `move_to_dlq()` + push error result (see #3).

This means `run_overflow_scanner` needs two new parameters: `max_retries` and `dlq_key`.

The retry count covers ALL attempts — local worker timeouts and RunPod failures both increment it. After 3 total failed attempts (any mix), DLQ.

### 3. TTS DLQ error notification

When a TTS job goes to DLQ (either from visibility scanner or overflow scanner at max retries):
- Parse the raw job as `SynthesisJob`
- Construct a `WorkerResult` with `error="Job failed after N retries"` and all required fields
- Push to `TTS_RESULTS`
- The result_consumer's existing `_handle_error` handles cleanup: delete inflight key, notify subscribers with error status, log `synthesis_error` metric

This applies in two places:
- `visibility_scanner.py` — existing DLQ path (add TTS handling next to YOLO handling)
- `overflow_scanner.py` — new DLQ path when RunPod fails at max retries

To avoid duplicating the WorkerResult construction, extract a helper (e.g., in `contracts.py` or a shared util).

## Considered & Rejected

- **`asyncio.gather` with `to_thread(run_sync)`** — each `run_sync` holds a thread for up to 60s. Default thread pool is ~20 threads. Doesn't scale to hundreds of overflow jobs. Makes the scanner itself the bottleneck.
- **Dedicated large thread pool for `run_sync`** — still threads, still a fixed limit. Band-aid over the wrong architecture.
- **Overflow-specific retry (re-submit to RunPod directly)** — special-casing. The normal retry flow (re-queue → visibility scanner tracks retries → DLQ) is cleaner and already exists.

## Discussion

Context from prod logs (Feb 4 2026): three large bursts of ~300 blocks each. Queue depths hit 260, queue waits exceeded 120s. The overflow scanner only managed to offload 6-8 jobs per burst because of its sequential design. One RunPod timeout (60s read timeout — likely cold start). Three "RunPod returned None" failures from a separate bug (fixed in 452e935, Jan 18 rewrite had broken the payload format).

Stress testing with 20 concurrent users × 30 blocks at 1.7x speed showed workers can't keep up (8 CPU workers produce ~2.1 blocks/s, consumption rate is 3.3-6.7 blocks/s). The overflow scanner is supposed to bridge this gap but currently can't because of the sequential bottleneck.
