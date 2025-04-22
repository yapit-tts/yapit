# Yapit

## 🚀 Mission & Goals
- **What:** A pluggable TTS service + UI (web + TUI) that reads text, web pages, PDFs with real‑time highlighting.
- **Why:** Enable seamless, accessible “read‑aloud” workflows for anyone (forever free tier of in-browser models), wanting to read website, pdfs, or any text.
- **Revenue:** Cheap monthly plans which unlock bigger/better models (with credit cap) and a persistent (cloud) library. Prepaid credits for GPU/CPU inference seconds to scale beyond that for enthusiasts

## 💡 Philosophy
- **OSS‑First Core:** Frontend, gateway, model‑adapters MIT/Apache‑2.0 (or GPL?).
- **Modular Adapters:** Hide each TTS engine (Kokoro, nari-labs/Dia-1.6B, ElevenLabsAPI?) behind a uniform API.  
- **Minimal Ops Overhead for Devs:** “Just docker-compose up” on CPU or GPU.
- **Zero overhead for paying users; Freedom for OSS tinkerers:** Options for self-hosted models, browser, cloud, or hybrid.
- **Pay‑for‑What‑You‑Use:** 1 credit 1 sec (or 1 char?, multiplier for more expensive models).

## 🏗️ Architecture

```text
[ React Web / TUI ]
        │        ▲
   REST & WS      │ ws: audio bytes + highlight events
        ▼        │
    [ FastAPI Gateway ]
        │        ▲
    Redis Lists  │ Redis Pub/Sub
        ▼        │
┌───────────────┐ ┌───────────────┐
│ OCR, VLLM     │ │ kokoro/dia    │  ← Docker images per core model | Serverless model inference
│ preprocessing │ │gpu|cpu workers│
└───────────────┘ └───────────────┘
        │            ← Main app on dedicated VPS
       Postgres      ← users, credits, jobs, voices
       MinIO/S3      ← PDF/website/text storage
```

(early draft)
- **Gateway**  
  - Stateless, uses FastAPI lifespan to open one Redis pool.  
  - Endpoints:  
    - `POST /v1/tts` → enqueue job + return `/ws/{id}`.  
    - `WS /ws/{id}` → stream binary frames.  
    - `GET /v1/voices` → voice metadata.  
    - `GET /healthz`.
- **Workers**  
  - `kokoro_worker.py` + `libs/kokoro_pipeline.py` which handle cpu/gpu workers.
- **Storage**  
  - **Redis:** queue + pub/sub + ephemeral offsets.  
  - **Postgres:** relational state, atomic credit debits.  
  - **MinIO (S3):** PDF blobs, etc. local in dev.

## 🔧 Current State (needs heavy refactoring & adaptations)
- ✅ Docker‑Compose skeleton (redis, postgres, minio, gateway, CPU/GPU workers).  
- ✅ Kokoro pipeline shared library, CPU & GPU images working.  
- ✅ Quick‑test script (`scripts/smoke_test.py`) writes `sample.wav`.  
- ✅ CI: GitHub Action builds all images on push.
- (in progress) React frontend scaffold [basic communication functionality]

## 🛠️ TODOs / Featurelist (loosely ordered, but can mostly be worked on in parallel)
1. **Gaetway / Backend**
   - ORM? If yes, SQLAlchemy+Alembic? 
   - Full API
2. **Auth & Billing**  
   - find a leaner / less bloated alternative to Zitadel; OIDC → JWT validation. Login with Google, Github.
3. **Frontend MVP**  
   - Voice/lang selector, play/pause, highlight.
   - Support for WebGPU models via transformers.js.
4. **Progress Persistence**  
   - Redis hash for offsets, periodic flush to Postgres.
   - Creidt / usage tracking.
5. **Additional Models**  
   - UI: Model selector 
6. **OCR, LLM & traditional parsing / filtering**
   - Support common document formats; VLLM-backed.
   - Support for web pages
7. **Payment Processing**  
   - Stripe integration for credit purchases.
   - Monthly subscription plans.
8. **Webhosting & Serverless Deployment**  
   - Deploy main app on dedicated VPS (e.g. Hetzner).
   - Serverless model inference (e.g. via runpod.io).
   - Persistent storage for user data (e.g. S3, Postgres).
9. **Testing & QA**  
   - Write unit tests for the core components? (at least for billing&auth)
   - Set up a staging environment for testing new features?
   - Implement monitoring and alerting for production systems.
10. ** Optimizations**
   - Opus encoding for audio streaming.
12. **Documentation & Community**  
    - Write a README for the repo (how to run it, how to self-host different models)
    - Create a Discord server for community support?
    - Write a blog post about the project.
13. **Ship it**
