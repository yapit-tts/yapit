---
status: done
started: 2026-01-03
completed: 2026-01-05
---

# Task: RunPod Overflow for Kokoro

## Decision

**CPU serverless** at $0.12/hr (4 vCPUs / 8GB RAM) — 5x cheaper than cheapest GPU.

## Endpoint Details

- **Endpoint ID:** `g5k5k3kra9ejik`
- **Compute:** CPU3 Compute-Optimized, 4 vCPUs, 8GB RAM
- **Cost:** $0.12/hr per worker
- **Max Workers:** 5
- **Scaling:** Scale to zero when idle

## Configuration

Deployed via RunPod GUI "Deploy from GitHub":
- **Repo:** yapit-tts/yapit
- **Branch:** main
- **Dockerfile:** `yapit/workers/kokoro/Dockerfile.cpu`
- **Build Context:** `.`
- **Docker Start Command:** `python -m yapit.workers.handlers.runpod`

**Environment Variables:**
- `DEVICE=cpu`
- `ADAPTER_CLASS=yapit.workers.adapters.kokoro.KokoroAdapter`
- `OMP_NUM_THREADS=4`

## Why CPU over GPU

Kokoro-82M is a tiny model (~200MB with voices):
- GPU minimum is 16GB VRAM — 80x more than needed
- CPU3 at $0.12/hr vs GPU A4000 at $0.576/hr
- Model baked into Docker image, no runtime download needed

## Config Files Updated

- `tts_processors.dev.json` — overflow endpoint ID
- `tts_processors.prod.json` — overflow endpoint ID
