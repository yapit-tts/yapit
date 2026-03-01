---
status: active
started: 2026-02-10
---

# Task: Overflow Tuning, jemalloc, Worker Memory Optimization

Related: [[stress-testing]], [[runpod-kokoro-overflow]]

## Intent

Tune the TTS overflow/visibility timers based on stress test data, and fix worker RSS creep (Kokoro workers growing from ~1.1GB to ~2.5GB and never shrinking).

## What Was Done

### Overflow/visibility timer tuning (commit `f90b09c`)

| Setting | Old | New | Rationale |
|---------|-----|-----|-----------|
| `TTS_OVERFLOW_THRESHOLD_S` | 30 | 15 | 15s > 10.4s (8-user drain time), so doesn't fire during normal 1-8 user operation. Catches overflow blocks 6-7 of first cold batch, blocks 3+ of warm batches. |
| `OVERFLOW_SCAN_INTERVAL_S` | 5 | 2 | Faster pickup, negligible overhead (one `zrangebyscore` call). |
| `TTS_VISIBILITY_TIMEOUT_S` | 30 | 20 | Worst-case synthesis ~7s for 300-char blocks. 20s = 3x headroom. False positive just causes duplicate work (deduped by inflight key). |
| `RUNPOD_REQUEST_TIMEOUT_SECONDS` | 60 | 25 | RunPod execution 4-8s, cold start p98=20s. 25s catches warm + most cold starts. Timeout → requeue → local worker or warm RunPod picks it up. |

### jemalloc for worker memory (commit `3f828ed`)

Installed `libjemalloc2` in both CPU and GPU Dockerfiles with `LD_PRELOAD` and `MALLOC_CONF=background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:1000`.

**Root cause of RSS creep:** glibc's `ptmalloc2` allocator uses per-thread arenas that fragment and never return freed pages to the OS. jemalloc uses size-class segregation + background decay purging to return freed memory.

**Observed result:** RSS climbs to ~1.5GB during diverse synthesis, settles back to ~1.1GB after activity stops. Previously it would climb to 2.5GB and stay there.

### ONEDNN_PRIMITIVE_CACHE_CAPACITY — tried and reverted (commit `3f828ed`, reverted in `7c98aa0`)

Initially set `ONEDNN_PRIMITIVE_CACHE_CAPACITY=16` thinking the oneDNN primitive cache was a major RSS contributor. This was wrong:

- Kokoro-82M needs ~25-35 unique oneDNN primitives per forward pass. A cache of 16 can't even hold one inference's worth of kernels → constant recompilation → ~2x synthesis slowdown.
- Each cached primitive is ~1-10 KB. Even default 1024 entries = ~1-10 MB. The oneDNN cache was never the source of the ~1GB growth.
- Reverted to default (1024). No performance regression with default cache.

### Stress test accuracy improvements (commit `f90b09c`)

- Real audio durations via OGG headers (mutagen) instead of hardcoded 4s
- Per-block `requested_ms` and `round_trip_ms` tracking
- Average metrics in summary output

## Assumptions

- VPS is cost-optimized shared hosting (EPYC, 2.4 GHz). Synthesis throughput varies ~20-35% across measurements, likely due to co-tenant load.
- Overflow threshold of 15s is tuned for 4 local Kokoro workers. Adding more workers (laptops, VPS) increases headroom — threshold could be raised.
- RunPod cold start p98 ~20s means first overflow batch has limited effectiveness. Subsequent warm batches benefit significantly.

## Key Findings

### VPS-only baseline (cost-optimized VPS, 4 CPU workers)

1-user 3x runs (6 data points, uniform blocks): first block 5.1-5.7s, RT avg 10.4-13.1s, 0 underruns. Multi-user: 3 users hits worker saturation (6-11 underruns), 5 users at 2x = 28 underruns, 299s total stall.

### Regular perf VPS vs cost-optimized (VPS-only, n=3 per scenario)

Upgraded from cost-optimized (older EPYC, limited availability) to regular performance (newer AMD, CPX62). Same spec: 16 vCPU, 32GB RAM. Disk upgrade 300GB→640GB.

| Scenario | Metric | Cost-optimized | Regular perf | Change |
|---|---|---|---|---|
| 1u/3x | First block | 4.5-5.3s | 4.2-4.8s | ~10% better |
| 1u/3x | RT avg | 10.1-12.0s | 9.8-10.7s | ~5% better |
| 3u/2x | RT avg | 33.2-35.3s | 29.8-33.0s | ~10% better |
| 3u/2x | Underruns | 9-11 | 6-8 | ~30% fewer |
| 5u/2x | RT avg | 48.2-58.0s | 39.9-44.0s | ~20% better |
| 5u/2x | Underruns | 21-33 | 21-26 | modest |
| 5u/2x | Underrun total | 257-314s | 118-246s | ~30-40% less stall |

Modest improvement. Variance ranges overlap at 1u. Main gains at 5u where less contention degradation. 1-2 users at 2x is smooth on either tier.

### GPU workers (2 GPU via Tailscale + 4 VPS CPU)

First attempt (Feb 19) revealed two gateway bottlenecks blocking GPU throughput:

1. **Connection pool starvation** — result consumer held Postgres connections for billing (FOR UPDATE lock), exhausting the shared pool. Fixed by hot/cold split: [[2026-02-19-result-consumer-billing-split]].
2. **SQLite cache.store serialization** — 40 concurrent cache writes serialized through one aiosqlite writer, each doing fsync on shared VPS storage. 99.9% of finalize time. Fixed by batched writes + in-memory notify buffer: [[2026-02-20-cache-store-hot-path]].

**Statistical validation (Feb 20 on cost-optimized VPS, n=3 per scenario, both fixes deployed):**

| Scenario | Setup | First block (best) | First block (worst) | RT avg | Underruns | Underrun total |
|---|---|---|---|---|---|---|
| 1u/3x | VPS only | 4.5-5.3s | — | 10.1-12.0s | 1 | 0.1-0.3s |
| 1u/3x | GPU+VPS | **0.6-1.5s** | — | **2.2-2.4s** | 1 | 3.1-4.2s |
| 3u/2x | VPS only | 4.6-5.0s | 5.1-9.5s | 33.2-35.3s | 9-11 | 63-74s |
| 3u/2x | GPU+VPS | **0.7-1.0s** | **1.1-1.3s** | **2.9-3.1s** | 2-3 | 4.4-10.9s |
| 5u/2x | VPS only | 5.5-9.3s | 10.6-14.4s | 48.2-58.0s | 21-33 | 257-314s |
| 5u/2x | GPU+VPS | **1.1s** | **1.3-2.2s** | **4.4-5.3s** | 3 | 3.1-8.8s |

**GPU improvement factors (comparing means across 3 runs):**
- 1u: first block 5.8x faster, RT avg 4.7x faster
- 3u: first block 5.7x faster, RT avg 11.4x faster, underruns 10→3, stall 70s→8s
- 5u: first block 6.3x faster, RT avg 10.3x faster, underruns 28→3, stall 279s→7s

### Gateway concurrency (Inworld, regular perf VPS)

Tested gateway/infrastructure scaling using Inworld TTS (external API, no local CPU bottleneck). This isolates gateway capacity from synthesis speed.

| Users | Blocks | Completed | RT avg | Underruns | Errors |
|---|---|---|---|---|---|
| 5 | 100 | 100 | 1.7s | 3 (1s) | 0 |
| 10 | 200 | 200 | 2.3s | 0 | 0 |
| 20 | 400 | 139 | 4.7s | 0 | 20 (Inworld rate limit) |

Gateway scales linearly to 10 concurrent users with zero issues. At 20u, the Inworld API rate limit (100 RPS default) is the bottleneck — 20 users × 8-block initial burst = 160 requests in ~1s. Requested increase to 1000 RPS.

## Sources

**Knowledge files:**
- [[tts-flow]] — Pipeline architecture, overflow mechanism, queue structure
- [[infrastructure]] — Docker compose structure, worker services

**Key code files:**
- MUST READ: `scripts/stress_test.py` — Stress test script, captures per-block metrics
- MUST READ: `yapit/gateway/overflow_scanner.py` — Overflow logic, RunPod submission/polling
- MUST READ: `yapit/workers/queue.py` — Redis queue ops (push, pull, requeue, visibility)
- Reference: `yapit/gateway/__init__.py:49-56` — Timer constants
- Reference: `yapit/workers/kokoro/Dockerfile.cpu` — jemalloc setup
- Reference: `yapit/workers/adapters/kokoro.py` — Synthesis adapter

**External docs:**
- Reference: [PyTorch #27971](https://github.com/pytorch/pytorch/issues/27971) — oneDNN cache memory growth (confirmed, but impact was overstated for small models)
- Reference: [PyTorch blog: optimizing LibTorch](https://pytorch.org/blog/optimizing-libtorch/) — jemalloc 34% peak memory reduction for inference
- Reference: [BetterUp: jemalloc fixed RSS creep](https://build.betterup.com/chasing-a-memory-leak-in-our-async-fastapi-service-how-jemalloc-fixed-our-rss-creep/) — RSS growth 10x reduction in async service

## Done When

- [x] Overflow/visibility timers tuned and deployed
- [x] Worker RSS creep fixed (jemalloc)
- [x] oneDNN cap evaluated (not needed, reverted)
- [x] Add varied text lengths to stress test (`--varied-lengths` flag, commit `a7b6f42`)
- [x] Collect baseline measurements on cost-optimized VPS
- [x] Benchmark with GPU workers — required fixing two gateway bottlenecks first (pool starvation, cache.store fsync)
- [x] Compare baselines on regular perf VPS after upgrade — modest 5-20% improvement, not dramatic
- [ ] Decide if OMP_NUM_THREADS experiment is worth pursuing
- [ ] Re-test 30 concurrent Inworld users once rate limit increase (1000 RPS) is approved
- [ ] Test MPS (Multi-Process Service) on single laptop GPU — how many Kokoro workers can one GPU serve?
- [ ] Test multiple laptops as GPU workers — what's the max Kokoro parallelism we can reach?

## Benchmarking Plan

**Current VPS:** Cost-optimized shared (EPYC, 2.4 GHz, 16 vCPU, 30GB RAM).

**Benchmark commands** (run `make prod-env` first if credentials are missing):
```
uv run scripts/stress_test.py --users 1 --blocks 20 --speed 3
uv run scripts/stress_test.py --users 3 --blocks 20 --speed 2
uv run scripts/stress_test.py --users 5 --blocks 20 --speed 2
```

Run all three as a batch. Results auto-save to `scripts/stress_test_results/` with timestamps.

For memory/RSS testing with diverse input shapes, add `--varied-lengths`:
```
uv run scripts/stress_test.py --users 1 --blocks 20 --speed 3 --varied-lengths
```

**Data collected so far (cost-optimized VPS, jemalloc, no oneDNN cap):**

| Date | Time | Scenario | Notes |
|------|------|----------|-------|
| Feb 10 22:54 | night | 1u/1x | Pre-deploy baseline (no jemalloc). Best reference point. |
| Feb 10 22:57 | night | 5u/1x | Pre-deploy multi-user baseline |
| Feb 11 18:46 | evening | 1u/1x | With jemalloc + oneDNN=16 (before revert) |
| Feb 11 18:51 | evening | 1u/3x | With jemalloc + oneDNN=16 |
| Feb 11 20:24 | evening | 1u/3x | With jemalloc, no oneDNN cap, cold workers |
| Feb 11 20:25 | evening | 1u/3x | Same config, warm workers |
| Feb 11 20:58 | evening | 1u/3x | With `--varied-lengths` |
| Feb 12 12:43 | midday | 1u/3x | |
| Feb 12 12:52 | midday | 3u/2x | |
| Feb 12 13:47 | afternoon | 5u/1x | |
| Feb 12 17:25 | late afternoon | 1u/3x | |
| Feb 12 17:42 | late afternoon | 3u/2x | |
| Feb 12 17:45 | late afternoon | 5u/2x | |
| Feb 13 00:19 | night | 1u/3x | |
| Feb 13 00:33 | night | 5u/1x | |
| Feb 16 19:00 | evening | 5u/1x | |
| Feb 16 19:11 | evening | 2u/3x | |
| Feb 19 16:31 | afternoon | 3u/2x | |
| Feb 19 21:36-21:57 | evening | 1u,3u,5u | GPU workers (pre billing split fix). Pool starvation: 5u worse than VPS-only. |
| Feb 20 01:21-01:26 | night | 1u,3u,5u | GPU + billing split. Modest improvement, cache.store bottleneck found. |
| Feb 20 05:28-05:31 | early morning | 1u,3u,5u | GPU + billing split + cache fix. Single run per scenario. |
| Feb 20 17:25-17:43 | afternoon | 1u×3,3u×3,5u×3 | **VPS-only post-fix statistical validation.** 3 runs per scenario. |
| Feb 20 19:38-19:50 | evening | 1u×3,3u×3,5u×3 | **GPU+VPS post-fix statistical validation.** 3 runs per scenario. |
| Feb 20 22:49-23:36 | night | 1u×3,3u×3,5u×3 | **Regular perf VPS (post-upgrade).** Modest improvement over cost-optimized. |
| Feb 21 00:13-00:15 | night | 5u,10u,20u (inworld) | **Gateway concurrency test.** 10u clean, 20u hit Inworld rate limit (100 RPS). |

**Next steps:**
1. ~~Connect PC as remote GPU worker~~ — Done (Feb 19). 2× RTX 3070 Ti Laptop GPU workers via Tailscale (no MPS).
2. ~~Statistical validation~~ — Done (Feb 20). 3 runs per scenario, both configs. Results consistent.
3. ~~Upgrade VPS to regular perf tier~~ — Done (Feb 20). CPX62 regular performance.
4. ~~Re-run benchmark suite on new VPS~~ — Done (Feb 20). ~5-20% improvement depending on scenario.
5. ~~Gateway concurrency test~~ — Done (Feb 21). Gateway not the bottleneck, scales linearly to 10u+.
6. Re-test 30 concurrent Inworld users after rate limit increase (requested 1000 RPS).

## Future: OMP_NUM_THREADS Experiment

Currently: `OMP_NUM_THREADS=2` with 4 Kokoro replicas (8 threads total on 16 vCPU).

**Hypothesis:** `OMP_NUM_THREADS=1` with more replicas could improve aggregate throughput under load. PyTorch uses OpenMP for intra-op parallelism (matrix multiplications). With `OMP_NUM_THREADS=2`, each worker has 2 threads coordinating via shared memory. Under 4+ concurrent workers, memory bus bandwidth contention degrades per-worker throughput.

With `OMP_NUM_THREADS=1` and more workers: each worker is single-threaded (no intra-op parallelism), but more independent workers. Intra-op parallelism has diminishing returns on Kokoro-82M (tiny matrices). Trade-off: slightly slower per-block synthesis (~800ms vs ~650ms?) but better aggregate throughput under contention.

**RAM constraint:** Each Kokoro worker uses ~2-2.5GB RSS (with jemalloc settling ~1.1GB hopefully). 8 workers = ~9-10GB just for Kokoro. Plus YOLO workers (~600MB × 4 = 2.4GB), gateway, Postgres, Redis. On a 30GB box: tight but feasible.

**Experiment plan:**
1. Establish baseline: current config (OMP=2, 4 replicas), multi-user stress tests
2. Change `.env.prod`: `OMP_NUM_THREADS=1`, `KOKORO_CPU_REPLICAS=6` (or 8 if RAM allows)
3. Same stress tests, compare
4. Key metrics: per-block synthesis time, aggregate throughput, underrun rate at 5-10 users
5. Monitor RSS to confirm jemalloc keeps memory in check with more workers

**Not urgent.** Current 4-worker setup handles 1-5 users fine. This matters when scaling to 8+ concurrent users without RunPod overflow.

## Considered & Rejected

- **`ONEDNN_PRIMITIVE_CACHE_CAPACITY=16`** — Caused ~2x synthesis slowdown. The cache is ~1-10MB total, not worth limiting. Reverted.
- **`MALLOC_TRIM_THRESHOLD_=0`** — glibc env var for aggressive memory return. Unnecessary with jemalloc (jemalloc replaces malloc entirely).
- **Periodic `gc.collect()` + `malloc_trim()`** — Belt-and-suspenders approach for glibc. Unnecessary with jemalloc.
- **RunPod min workers = 1** — Eliminates cold start but costs ~$86/month for always-on worker. Defeats purpose of serverless overflow. Better to connect local machines for free baseline capacity.
- **Queue-depth-based overflow** — Unnormalized metric with dynamic worker capacity. Time-based threshold (15s) is self-normalizing: a job stuck 15s is genuinely overloaded regardless of worker count.
