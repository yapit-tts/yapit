---
status: done
type: research
---

# Task: Kokoro CPU Thread/Instance Benchmarking

**Knowledge extracted:** [[architecture]] (Infrastructure Decisions table + TODO list)

## Goal

Empirically determine optimal thread and replica configurations for Kokoro TTS inference:
1. Python Kokoro: Measure latency/throughput at OMP_NUM_THREADS = 1, 2, 4
2. Rust Kokoros: Measure latency/throughput at --instances = 1, 2, 4

This informs decisions about:
- How many threads per Docker replica to allocate
- Whether Rust Kokoros offers meaningful performance gains
- Expected scaling behavior on VPS (16 vCPU shared) vs local (i9-12900H)

## Context

From discussion:
- i9-12900H: 6 P-cores (5GHz boost) + 8 E-cores = 14 cores, 20 threads
- Current setup: Docker replicas with PyTorch Kokoro, NOT setting OMP_NUM_THREADS (defaults to all cores, wasteful)
- RAM not a constraint (32GB), so Docker replicas preferred over in-process parallelism
- Kokoros (Rust) uses ONNX, has --instances flag for parallel workers within one process

Expected findings based on theory:
- Small models (82M params) don't benefit from many threads
- OMP_NUM_THREADS=1-2 likely optimal per replica
- Docker replicas scale better than --instances (separate memory spaces)
- Memory bandwidth and L3 cache thrashing limit scaling at high replica counts

## Constraints / Design Decisions

- Benchmark scripts should be standalone (can run outside Docker)
- Use realistic text lengths (paragraph-sized, similar to actual workload)
- Measure both single-inference latency and concurrent throughput
- Report real-time factor (audio_duration / synthesis_time)

## Next Steps

1. Run Python benchmark on local machine:
   ```bash
   uv run scripts/tts_speed_benchmark/thread_benchmark.py
   # Or with specific thread counts:
   uv run scripts/tts_speed_benchmark/thread_benchmark.py --threads 1 2 4
   ```

2. For Rust benchmark, first set up Kokoros:
   ```bash
   git clone https://github.com/lucasjinreal/Kokoros
   cd Kokoros
   bash download_all.sh  # downloads model and voices
   cargo build --release
   export KOKOROS_DIR=$(pwd)
   ```
   Then run benchmark:
   ```bash
   uv run scripts/tts_speed_benchmark/kokoros_benchmark.py
   ```

3. Compare results, document findings in Notes/Findings

4. Apply OMP_NUM_THREADS fix to Dockerfile based on results

## Open Questions

- Should we also benchmark concurrent replicas (multiprocessing) in Python, or is thread count sufficient for now?
- Rust Kokoros: need to verify it builds and produces quality audio before using results

## Notes / Findings

**Python Kokoro thread scaling (RTF = audio_duration / synthesis_time):**

| Threads | Medium latency | RTF |
|---------|----------------|-----|
| 1 | 5229ms | 1.6x |
| 2 | 2941ms | 2.9x |
| 3 | 2349ms | 3.7x |
| 4 | 1806ms | 4.8x |
| 8 | 2212ms | 3.9x |

T=4 is the local optimum. Power-of-two might matter (SIMD alignment or cache effects).

**Rust Kokoros instance scaling:**
- I=1: 4.6x RTF
- I=2: 3.6x RTF (SLOWER)
- I=4: 3.4x RTF (even worse)

Rust offers no advantage - gets slower with more instances due to internal contention.

**16 vCPU deployment options:**

| Config | Concurrent | Latency | Throughput |
|--------|------------|---------|------------|
| 4t × 4r | 4 | ~1800ms | ~2.2 req/s |
| 2t × 8r | 8 | ~2900ms | ~2.8 req/s |

- **4×4**: Latency-optimized
- **2×8**: Throughput-optimized

**Decision:** Set `OMP_NUM_THREADS=4` in Dockerfile.cpu. Tune replicas separately based on deployment needs.

**MKL:** Verified PyTorch build doesn't use MKL, only OMP_NUM_THREADS needed.

---

**VPS Benchmarks (8 vCPU shared Hetzner):**

| Threads | Latency (medium) | RTF |
|---------|------------------|-----|
| 1 | 8423ms | 1.0x |
| 2 | 4570ms | 1.9x |
| 4 | 2635ms | 3.3x |
| 6 | 2074ms | 4.2x |
| 8 | 1674ms | 5.2x |

VPS scales differently than i9 - no diminishing returns at high thread counts. Server CPUs handle T=8 better than hybrid i9 (no P-core/E-core scheduling issues).

**TODO: Test for prod on 16 vCPU:**
- T=8 × 2 replicas vs T=4 × 4 replicas
- Compare UX: latency difference vs throughput tradeoff
- T=8×2: lower latency per request, fewer concurrent requests
- T=4×4: higher latency, better load distribution

---

## Work Log

### 2025-12-28 - Initial Setup

Creating benchmark scripts based on conversation context:
- Python benchmark: Vary OMP_NUM_THREADS, measure single-inference latency
- Rust benchmark: Vary --instances, measure throughput via OpenAI-compatible API

User explicitly said not to use memex for this task.

### 2025-12-28 - Scripts Created

Created two benchmark scripts:

1. `scripts/tts_speed_benchmark/thread_benchmark.py`
   - Tests OMP_NUM_THREADS = 1, 2, 4, 8 (configurable)
   - Spawns subprocess for each thread count (env vars must be set before torch import)
   - Tests short/medium/long texts
   - Reports mean latency, real-time factor, relative speedup vs T=1
   - 10 iterations per config with warm-up run

2. `scripts/tts_speed_benchmark/kokoros_benchmark.py`
   - Tests Rust Kokoros with --instances = 1, 2, 4 (configurable)
   - Manages server lifecycle (start/stop for each instance count)
   - Uses OpenAI-compatible API endpoint
   - Same test texts and metrics as Python benchmark
   - Requires KOKOROS_DIR env var or --kokoros-dir flag

Both scripts save JSON results to `scripts/tts_speed_benchmark/results/`.

### 2025-12-29 - Archived

Knowledge extracted to architecture.md:
- Added `OMP_NUM_THREADS=4` decision to Infrastructure Decisions table
- Added TODO for testing T=8×2 vs T=4×4 on 16 vCPU production

Commits made:
- `fix: limit Kokoro CPU threads for better replica scaling` (Dockerfile.cpu change)
- `chore: remove Rust Kokoros benchmark script` (deleted kokoros_benchmark.py)

Cleanup:
- Deleted Kokoros/ cloned repo
- Deleted comparison audio samples and benchmark result JSONs from this task
