---
status: active
started: 2026-01-15
---

# Task: Worker Architecture Rewrite

## Intent

Redesign the TTS/processing worker architecture to support heterogeneous workers (home GPU, VPS CPU, RunPod, dedicated servers) that can be added or removed dynamically without code changes or gateway restarts.

The current architecture has the gateway pulling from Redis queues and calling workers via HTTP. This creates tight coupling — the gateway needs to know worker URLs, manage routing, handle HTTP overhead, and can't easily load-balance across workers with different speeds.

The new architecture inverts control: workers pull jobs from Redis directly, process them, and push results back. The gateway only pushes jobs and consumes results. Workers become truly independent — just connect to Redis and start pulling.

## Goals

1. **Any device can be a worker** — Home PC with GPU, VPS, RunPod pod, dedicated server. Just needs Redis access (via Tailscale).

2. **Natural load balancing** — Faster workers pull more jobs automatically. No round-robin configuration needed. A GPU that finishes in 100ms pulls 20x more than a CPU that takes 2 seconds.

3. **Zero gateway changes to add workers** — Spin up a new worker anywhere, point it at Redis, done. No config files to update, no deploys.

4. **Simpler code** — Delete the processor class hierarchy, HTTP worker handlers, routing logic. Replace with one small worker loop function and one result consumer.

5. **Unified approach** — Same pattern for TTS (Kokoro, Higgs) and other processing (YOLO). Different adapters, same worker infrastructure.

## Architecture

```
Gateway                              Workers (anywhere)
───────                              ─────────────────
Push jobs to                         Pull from Redis
tts:queue:{model}  ──────────────►   (via Tailscale)
                                            │
                                            ▼
                                     Process (synthesize/detect)
                                            │
                                            ▼
                   ◄──────────────   Push to tts:results
Consume results
Write to DB
Notify subscribers
```

**Workers only need Redis access.** No Postgres, no HTTP endpoints. Gateway handles all DB writes and notifications centrally.

**Single result queue** — All workers push to `tts:results` (or `yolo:results`). Gateway runs a result consumer that finalizes.

## Key Decisions

### Workers pull, don't receive

The fundamental change. Workers are active (pull work) not passive (receive HTTP calls). This enables:
- Any number of workers without gateway knowing about them
- Natural load distribution based on processing speed
- Workers can come and go without coordination

### No classes for worker loop

The worker is a simple async function, not a class hierarchy. Something like:

```python
async def run_worker(redis_url, queue, adapter):
    # pull job, process, push result — that's it
```

Adapters (KokoroAdapter, YoloAdapter) are still classes because they have state (loaded models), but the worker loop itself is just a function.

### Configuration via environment variables

No JSON config files for workers. Each worker gets:
- `REDIS_URL` — where to connect
- `QUEUE` — which queue to pull from
- `ADAPTER_CLASS` — what adapter to use

Gateway doesn't need worker config at all — it just pushes to `tts:queue:{model_slug}`. The model slug comes from the database.

### Redis AUTH for security

Workers connect via Tailscale (private network) + Redis password. Defense in depth without complexity.

### Tailscale for networking

VPS and home machines join the same Tailnet. Workers connect to Redis via Tailscale IP. No port forwarding, no public endpoints, automatic encryption.

## What Gets Deleted

- `gateway/processors/tts/local.py` — HTTP caller
- `gateway/processors/tts/runpod.py` — RunPod SDK caller
- `gateway/processors/tts/inworld.py` — Inworld becomes an adapter in a worker, not a gateway processor
- `gateway/processors/tts/manager.py` — route management
- `gateway/processors/tts/base.py` — processor base class
- `tts_processors.*.json` — all routing config files
- `workers/handlers/local.py` — HTTP server for workers
- `workers/handlers/runpod.py` — RunPod serverless handler
- `asyncio.Lock` in adapters — with one-job-at-a-time per worker process, no concurrency within process, lock is unnecessary

## What Gets Added

- `workers/queue_pull.py` — generic worker loop (~40 lines)
- `workers/adapters/inworld.py` — Inworld adapter (moved from gateway processor)
- `gateway/result_consumer.py` — consumes results, finalizes (~50 lines)
- Redis AUTH configuration
- Worker Redis connection handling — reconnect with backoff on connection loss, health check endpoint for container orchestration

## What Stays

- `workers/adapters/*.py` — the actual synthesis/detection logic (unchanged)
- Queue/deduplication logic in `ws.py` — still pushes to Redis queues
- `finalize_synthesis` logic — moves to result consumer but logic unchanged

## Bugs to Fix During Rewrite

### Overflow blocking

Current overflow code awaits RunPod calls synchronously in the request handler loop. Each block waits for the previous to complete. This defeats the purpose of overflow.

In new architecture: not applicable — workers pull independently, no overflow concept needed. If queue is deep, spin up more workers.

### Semaphore bottleneck

Current worker has `Semaphore(2)` limiting concurrency. With new architecture, concurrency is controlled by number of worker processes, not semaphores.

## Migration

Clean break, not gradual. Create feature branch, delete old code, implement new architecture, test, merge.

RunPod serverless becomes RunPod pods (or not used at all if home GPU is sufficient). The serverless cold-start problem goes away with always-on workers.

## Sources

**Knowledge files:**
- [[tts-flow]] — current synthesis pipeline (will be simplified)
- [[infrastructure]] — deployment setup (Docker Swarm, Tailscale addition)

**Key code to understand before implementing:**
- `gateway/processors/tts/base.py:finalize_synthesis` — logic that moves to result consumer
- `gateway/api/v1/ws.py:_queue_synthesis_job` — queue pushing logic (mostly stays)
- `workers/adapters/kokoro.py` — adapter interface (unchanged)
- `contracts.py` — job/result message types (may need new result message type)

## First-Class Observability

Logging and metrics are not afterthoughts. Build them in from the start.

### Logging

Every significant event gets a log line:
- Worker started, connected to Redis
- Job pulled from queue (job_id, queue, worker_id)
- Processing started (job_id, text_length)
- Processing completed (job_id, duration_ms, audio_duration_ms)
- Processing failed (job_id, error, stack trace)
- Result pushed (job_id)
- Result consumed by gateway (job_id)
- Finalization complete (variant_hash, user_id)

Use structured logging (JSON) so logs are queryable. Include correlation IDs (job_id flows through entire pipeline).

### Metrics

Key metrics to track:
- Queue depth per model (gauge)
- Jobs processed per worker (counter)
- Processing latency (histogram)
- Audio duration vs processing time ratio (are we faster than realtime?)
- Error rate per worker/model
- Result queue depth (should stay near zero — if growing, gateway can't keep up)

Can defer metric instrumentation to after core functionality works, but design with metrics in mind.

## Decisions Made

### Serverless as fallback

Primary capacity: pull-based workers (VPS, home GPU, connected machines via Tailscale).

Fallback: when queue depth exceeds threshold and isn't draining fast enough, gateway falls back to HTTP calls to RunPod serverless. Same concept as current overflow, but now overflow is the only HTTP path.

This keeps auto-scaling benefits of serverless without paying for always-on pods.

### Result queue structure

- `tts:results` — one queue for all TTS models (same finalization logic, distinguish by model_slug in message)
- `yolo:results` — separate queue (different processing type, different finalization)

Job queues remain per-model (`tts:queue:kokoro`, `tts:queue:higgs`) for routing and queue depth metrics.

## Patterns to Preserve

These work well — keep the concepts even if implementation changes:

1. **Variant hash deduplication** — Same text + model + voice = same hash. Check cache, subscribe to in-flight, share results across users.

2. **Subscriber notification via pubsub** — Multiple blocks subscribe to a variant. On completion, notify all via Redis pubsub.

3. **Pending set for cursor eviction** — Track pending blocks per user/document. Evict outside playback window.

4. **Usage check before, record after** — Check limits when queuing, record usage on finalization.

5. **HIGGS context tokens** — Pass audio tokens from previous blocks for voice consistency.

## Improvement Opportunities

1. **SQLite cache is synchronous** — Blocks event loop. Consider `aiosqlite` or `run_in_executor` wrapper.

2. **Include usage_multiplier in job** — Currently finalize_synthesis queries DB for this. Include in job to avoid extra query.

3. **Consolidate Redis keys** — Current sprawl: `TTS_INFLIGHT`, `TTS_SUBSCRIBERS`, `tts:pending:*`, `tts:queue:*`, `tts:done:*`. With visibility timeout, some change. Document the new key structure clearly.

### Job recovery on worker crash

Use visibility timeout pattern with dead letter queue:

1. Pop job → move to `processing:{worker_id}` set with timestamp + retry count
2. Worker finishes → delete from processing set
3. Background task (every ~30s): jobs stuck > 60s → re-queue, increment retry count
4. Retry count > 3 → move to `tts:dlq`, stop retrying

Why not accept loss: buffering logic fetches ~8 blocks ahead at ~10s each. 5 minute inflight TTL far exceeds the ~80s buffer runway — playback would stall.

Why DLQ: prevents poison messages (malformed input causing crashes) from spinning forever. Can inspect and fix or discard.
