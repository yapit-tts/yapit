---
status: active
started: 2026-02-11
---

# Task: Remove YOLO RunPod Overflow, Reallocate to Kokoro

Related: [[2026-02-11-overflow-tuning-jemalloc-worker-memory]], [[runpod-kokoro-overflow]]

## Intent

YOLO overflow to RunPod serverless isn't pulling its weight. Remove it and give those RunPod workers to Kokoro TTS, where overflow actually matters for user experience.

## Why YOLO overflow isn't worth it

1. **Not latency-sensitive.** YOLO runs during document extraction — user sees a progress bar. 20s vs 50s per page is barely noticeable in the overall extraction time (Gemini is the bottleneck, not YOLO).

2. **Cold start defeats the purpose.** RunPod serverless cold start p98 ~20s. By the time a cold YOLO worker spins up, the local workers have already chewed through more of the queue. Historical evidence: Feb 7 stress test — 50 overflow jobs sent to RunPod, all timed out at 60s. Feb 11 stress test — 60+ overflow jobs, 104 timeouts at 25s.

3. **10s threshold fires too eagerly.** With 4 local YOLO workers processing ~4 pages at a time, a 100-page burst immediately exceeds the 10s threshold for most jobs. The scanner floods RunPod with cold-start requests that mostly time out and get requeued anyway.

4. **For sustained load, local workers are the answer.** If YOLO consistently can't keep up, adding another local CPU worker (or a GPU worker via Tailscale) gives predictable throughput without cold start. RunPod serverless burst capacity doesn't solve a sustained throughput problem.

## Why Kokoro overflow IS worth it

TTS is latency-sensitive — user is actively listening. Audio buffering = perceptible stalling. Even with cold start latency, getting an audio chunk 15-20s late is better than the playback engine underrunning. RunPod overflow is a real-time safety net for burst capacity.

Current Kokoro RunPod config: max 5 workers. Reallocating the YOLO budget would allow raising this (exact number depends on RunPod endpoint config — both endpoints are the same $0.12/hr CPU3 tier).

## What changes

No code changes. The scanner is already gated by `if settings.yolo_runpod_serverless_endpoint:` — just disable via config.

1. **Unset `YOLO_RUNPOD_SERVERLESS_ENDPOINT`** from prod env (sops). Scanner won't start.
2. **Deactivate YOLO RunPod endpoint** (`85nhen5anr416f`) via RunPod UI.
3. **Raise Kokoro max workers** on RunPod endpoint (`g5k5k3kra9ejik`) — from 5 to 7 (or whatever the freed budget allows).

## Considerations

**YOLO queue behavior after removal:** With no overflow, a burst of 100+ pages just queues up for local workers. 4 YOLO CPU workers process ~4 pages concurrently. A 100-page doc takes ~25 pages/worker = ~50-75s total YOLO time (depending on page complexity). Gemini extraction runs in parallel per-page-as-YOLO-completes, so the user still sees steady progress bar movement. Acceptable.

**No code changes to gemini.py needed.** The extraction pipeline doesn't know or care about overflow — it enqueues YOLO jobs and waits for results via BRPOP. Whether results come from local workers or RunPod is transparent. Removing overflow just means all results come from local workers (slower for burst, but reliable).

**YOLO visibility scanner stays.** It handles a different problem: jobs that were claimed by a worker but never completed (worker crash). It requeues them. Independent of RunPod — works with local workers only.

**Reversible.** If we later need YOLO overflow (e.g., many concurrent users uploading large PDFs), re-enable by setting `yolo_runpod_serverless_endpoint` in env and adding the scanner task back. The handler code is still there.

## Sources

**Knowledge files:**
- [[tts-flow]] — TTS pipeline, why latency matters there
- [[document-processing]] — YOLO's role in extraction pipeline

**Key code files:**
- MUST READ: `yapit/gateway/__init__.py` — Scanner task creation, constants
- MUST READ: `yapit/gateway/config.py:25-28` — RunPod settings
- Reference: `yapit/gateway/overflow_scanner.py` — Generic scanner (no changes needed)
- Reference: `yapit/workers/handlers/yolo_runpod.py` — Handler to keep but not use
- Reference: `.env.template` — Template vars to clean up

**Tasks:**
- [[2026-02-11-overflow-tuning-jemalloc-worker-memory]] — Recent overflow timer tuning, stress test baselines
- [[runpod-kokoro-overflow]] — Kokoro RunPod endpoint config, pricing

## Done When

- [ ] `YOLO_RUNPOD_SERVERLESS_ENDPOINT` unset from prod env (sops)
- [ ] YOLO RunPod endpoint deactivated (RunPod UI — manual)
- [ ] Kokoro max workers raised (RunPod UI — manual)
- [ ] Stress test with 100-page PDF confirms extraction completes without overflow (slower but stable)
