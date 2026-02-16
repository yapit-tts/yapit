---
status: active
started: 2026-01-20
---

# Task: External GPU Worker Setup

## Intent

Enable connecting arbitrary GPU machines (personal laptops/desktops, Hetzner 1080s, etc.) to the production system via Tailscale + Redis. The goal is a simple script that sets up MPS, configures threads, and launches workers with minimal friction.

The architecture already supports this (pull-based workers just need Redis access), but we lack:
1. Documentation of the setup workflow
2. A setup/launch script
3. GPU Dockerfiles (YOLO GPU doesn't exist, Kokoro GPU may be stale)

## Assumptions

- External workers connect via Tailscale (already in use for VPS ↔ Redis)
- MPS is worth enabling on any GPU for small models (82M Kokoro + 20M YOLO = ~600MB VRAM)
- Workers run as Docker containers with `--restart=unless-stopped`
- MPS daemon runs on host, not in container

## Performance Findings (2026-01-20)

Benchmarked on laptop (i9-12900H) and VPS (EPYC Rome 16 cores):

### CPU Thread Scaling

| Threads | Time/image | Speedup |
|---------|------------|---------|
| 1       | 3468ms     | 1.0x    |
| 2       | 1871ms     | 1.9x    |
| 4       | 1092ms     | 3.2x    |
| 6       | 944ms      | 3.7x    |
| 8       | 1322ms     | 2.6x (regression!) |

**Takeaway:** `OMP_NUM_THREADS=2` for parallel workers. Beyond ~6 threads, memory bandwidth becomes the bottleneck (~22.6 GB/s on VPS).

### Parallel Workers (CPU)

| Config | Per-image (isolated) | Per-image (contended) | Throughput |
|--------|---------------------|----------------------|------------|
| 4×4    | 1092ms              | ~3065ms              | ~1.3 img/s |
| 8×2    | 1871ms              | ~4734ms              | ~1.7 img/s |

8×2 wins slightly on throughput but both hit memory bandwidth hard. **Critical:** Must set `OMP_NUM_THREADS` explicitly — PyTorch defaults to all cores per process, causing 47 threads per worker fighting over 16 cores.

### GPU Considerations

- **MPS (Multi-Process Service):** Allows multiple workers to share GPU without full context switches. `nvidia-cuda-mps-control -d` on host, workers just run normally.
- **Time-sharing overhead:** ~1-5ms per context switch. Negligible for bursty traffic.
- **When MPS helps:** Small models that don't saturate GPU, bursty traffic, want low latency without batching.
- **Caveat:** One process crash can affect others sharing MPS. Use process supervisor.
- **Our models fit easily:** 20M YOLO (~200MB) + 82M Kokoro (~400MB) = ~600MB total. 1080 has 8GB.

## Done When

- [ ] Setup script exists that:
  - Starts MPS daemon (if GPU present)
  - Connects to Redis via Tailscale
  - Launches specified number of workers
  - Sets `OMP_NUM_THREADS` appropriately
- [ ] YOLO GPU Dockerfile exists
- [ ] Kokoro GPU Dockerfile tested/updated if stale
- [ ] Workflow documented in knowledge base

## Gaps to Address

### YOLO GPU Support

Current `yolo/__main__.py` hardcodes `device="cpu"`:
```python
results = _model.predict(img, imgsz=IMGSZ, conf=CONF_THRESHOLD, device="cpu", verbose=False)
```

Need to:
1. Make device configurable via env var
2. Create `Dockerfile.gpu` for YOLO

### Kokoro GPU Dockerfile

`yapit/workers/kokoro/Dockerfile.gpu` exists but may be stale:
- Uses CUDA 12.8.1 / Ubuntu 24.04
- Uses `pyproject.gpu.toml` (does this exist and is it current?)
- Last tested: unknown

### MPS Trade-offs

**Downsides of enabling MPS on personal machine:**
- If one CUDA process crashes/corrupts memory, can take down others
- MPS daemon needs root to start
- Slight overhead when GPU isn't busy (negligible)

**When NOT to use MPS:**
- Single worker per GPU (no benefit)
- Models that saturate GPU alone (no room to interleave)
- Paranoid about crash isolation

For our use case (small models, multiple workers, bursty traffic) → MPS is a clear win.

## Sources

**Knowledge files:**
- [[tts-flow]] — Worker architecture, queue structure
- [[infrastructure]] — Docker setup, Tailscale

**Key code:**
- MUST READ: `yapit/workers/tts_loop.py` — TTS worker implementation
- MUST READ: `yapit/workers/yolo/__main__.py` — YOLO worker (needs GPU support)
- Reference: `docker-compose.kokoro-gpu.yml` — existing GPU compose
- Reference: `yapit/workers/kokoro/Dockerfile.gpu` — existing GPU Dockerfile

## Considered & Rejected

(None yet)

## Discussion

Initial context from performance investigation session exploring DocLayout-YOLO inference characteristics and optimal parallelization strategies.
