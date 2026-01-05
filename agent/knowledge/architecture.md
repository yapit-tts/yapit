
[TODO: Turn this into a tracking issue for tracking issues... so the agent can recursively explore what's relevant, instead of having this stale slop + stuff that could be easily gathered with tre + git log or reading the Makefile/actual code itself (never stale)]
[Already cleaned it up a bit, extracted todos into tasks, corrected stale info manually, but might want to rewrite progressively or at a later point in a focussed effort]

# Yapit TTS - Architecture Overview

## Mission
Open-source TTS platform for reading documents, web pages, and text with real-time highlighting.
- **Free tier**: Browser-side TTS via Kokoro.js (82M param model, runs locally in WASM/WebGPU) - zero server cost
- **Paid tier**: Server-side models via RunPod (higher quality, supports higgs-audio-v2)

### Target Audience
- People who want to listen to documents hands-off while doing other things
- People who want to read + listen simultaneously for better concentration
- People who want **accurate content** - not a podcast, not summarized, the actual document
- Researchers, students, anyone reading papers/articles/book chapters
- Secondary: Accessibility for users who prefer audio

### Version Definitions

**Note**: Informal priority indicators, not tracked releases.

- **v0** ✅: Basic working loop - audio plays, play/pause, block highlighting, click-to-jump
- **v0.x** ✅:: Polish UX/UI, voice picker, speed control, position memory, model tuning
- **v1** (~✅): All essential features + billing/Stripe, ready for beta testers
- **v1.x**: add release workflow (main, dev), monitoring, admin panel, self-host docs
- **Ship**: Dogfooding complete, proper deploy pipeline (Hetzner + Cloudflare + RunPod?)

---

## MarkItDown vs Markdown Parser


```
PDF/DOCX/HTML  →  MarkItDown  →  Markdown string
```

```
Markdown string  →  parse_markdown()  →  AST  →  transform_to_document()  →  StructuredDocument JSON
```

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Structured content format | **JSON** (not XML) | Native to React frontend, Pydantic serializes trivially |
| Markdown parsing location | **Backend (Python)** | Keep frontend thin, reuse for API consumers |
| Block highlighting MVP | **Highlight current block only** | TTS models don't return character timing; sentence-level adds complexity |
| Block splitting priority | Markdown structure → paragraphs → sentences → hard cutoff | Respect document semantics, never split mid-code-block |
| Serverless TTS | **No vLLM** | ~170s cold start unacceptable, use plain HF inference |
| Authentication | **Stack-Auth** | Already integrated, version pinned |
| Caching | **SQLite** | Simple, works for single-instance deployment |
| Anonymous sessions | **Yes, backend storage** | Generate UUID on first visit, store in DB with `anon-{uuid}` user_id. Simpler than IndexedDB dual-path. |
| Design philosophy | **Iterate by doing** | Don't over-plan upfront, ship and get feedback |
| Theme | **Light/cozy Ghibli** | Warm cream, green primary, wood/elven aesthetic. Theme customization post-launch |

---

## Infrastructure & Hosting

### Production Architecture

```
Cloudflare (free tier)
├── DNS
├── CDN (static assets, Kokoro.js model cached at edge)
└── Proxy to origin
         ↓
Hetzner VPS (single box)
├── Caddy/nginx (reverse proxy + static frontend)
├── FastAPI gateway
├── PostgreSQL
├── Redis
├── Kokoro CPU workers
└── SQLite audio cache (local SSD)
         ↓                                                       ↓
RunPod (serverless, on-demand)
└── GPU workers (currnelty (TBD) kokoro overflow) └── Inworld TTS API ("premium voices")
```

### Key Infrastructure Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hosting | **Hetzner VPS** | Best price/performance, EU-based, easy upgrades |
| CDN | **Cloudflare free** | Caches static assets + Kokoro model globally, US users served from edge |
| Object storage (S3/R2) | **Not needed** | No persistent file storage required - text stored in Postgres, audio cache ephemeral |
| Audio cache | **Local SSD (SQLite)** | Session buffer, not permanent archive. LRU eviction, 7-14 day TTL |
| CPU inference | **On VPS** | Marginal cost = $0 (already paying for box). RunPod CPU only if VPS maxed |
| GPU inference | **RunPod serverless** | Pay-per-use for premium models, no 24/7 GPU cost |
| Kokoro CPU threads | **OMP_NUM_THREADS=4** | Benchmarked optimal per replica. VPS scales well to T=8 (no hybrid core issues like i9). See `kokoro-cpu-benchmarking.md` for data. |

### Cache Strategy

Audio cache is a **session buffer**, not a permanent archive:
- Users read unique documents (low cross-user cache hits)
- Voice permutations explode keyspace (text × voice × settings)
- Documents are ephemeral (read once, rarely revisited)
- LRU eviction with size cap (~20-50GB based on SSD budget?)
- TTL: ~7-14 days for untouched entries?
- Loss tolerance: High (audio can be regenerated)

## Document Processing Flow (Implemented)

```
1. Input (URL/upload/text)
      │
      ▼
2. MarkItDown (for PDF/DOCX/HTML)    OR    Raw text (for text input)
      │                                           │
      └────────────────┬──────────────────────────┘
                       │
                       ▼  markdown text string
3. Markdown Parser (markdown-it-py)
      │  - parse_markdown() → SyntaxTreeNode AST
      │  - Location: yapit/gateway/processors/markdown/parser.py
      │
      ▼
4. Document Transformer
      │  - transform_to_document() → StructuredDocument
      │  - Creates typed blocks (heading, paragraph, list, code, math, table, etc.)
      │  - Splits large paragraphs at sentence boundaries
      │  - Assigns audio_block_idx (number for prose, null for non-prose)
      │  - Location: yapit/gateway/processors/markdown/transformer.py
      │
      ├──────────────────────────────────────────┐
      │                                          │
      ▼                                          ▼
5a. Audio Blocks (DB)                      5b. structured_content (JSON)
    - get_audio_blocks() extracts              - Full StructuredDocument JSON
      plainText from prose blocks              - Stored in Document model
    - Stored as Block records                  - Used by frontend
    - Each maps to one audio_block_idx
      │                                          │
      ▼                                          ▼
6. TTS Synthesis                           7. Frontend Rendering
    - Server-side or browser                   - StructuredDocumentView component
    - Per audio block                          - Type-based block renderers
                                               - Active block highlighting
                                               - Click-to-jump playback
```

---

## Backend Architecture

### API Endpoints (`yapit/gateway/api/v1/`)

**Documents:**
- `POST /documents/prepare` - Download URL, extract metadata, cache, return hash + cost estimate
- `POST /documents/prepare/upload` - Same for file uploads
- `POST /documents/text` - Create from direct text input
- `POST /documents/website` - Create from URL (fetches, parses, creates document)
- `POST /documents/document` - Create from PDF/DOCX with optional OCR
- `GET /documents/{id}` - Get document
- `GET /documents/{id}/blocks` - Get all blocks for playback

**TTS (WebSocket):**
- `WS /v1/ws/tts` - WebSocket for synthesis control (see below)

**Audio:**
- `GET /v1/audio/{variant_hash}` - Fetch cached audio by variant hash
- `POST /v1/audio` - Submit browser-synthesized audio for caching

### TTS Architecture: Model + Mode Separation

**Core concept**: Model identity and deployment mode are separate concerns.

**Model** (what): `kokoro`, `higgs` — the actual TTS model
**Mode** (where): `browser`, `server` — where synthesis happens

**DB stores models**, not deployment combinations:
- One `TTSModel` entry per actual model (kokoro, higgs)
- `is_paid` property on processors determines if usage is metered (browser mode = always free)

**Routing** is config-driven (`tts_processors.*.json`):
```json
{
  "model": "kokoro",
  "mode": "server",
  "backend": {"processor": "LocalProcessor", "worker_url": "..."},
  "overflow": {"processor": "RunpodProcessor", ...}
}
```

### TTS Processors (`yapit/gateway/processors/tts/`)

| Processor | Purpose |
|-----------|---------|
| LocalProcessor | Server-side via local HTTP worker (Kokoro on VPS) |
| RunpodProcessor | Serverless via RunPod API (HIGGS, overflow) |

**Overflow routing**: When queue depth exceeds threshold, requests route to overflow processor (e.g., RunPod serverless).

### WebSocket Synthesis Flow (Server Mode)

```
Frontend                    Gateway                     Workers
   |                           |                           |
   |--WS connect + auth------->|                           |
   |                           |                           |
   |--{type: "synthesize",     |                           |
   |   blocks: [0,1,2...],     |                           |
   |   model: "kokoro",        |                           |
   |   voice: "af_heart"}----->|                           |
   |                           |                           |
   |                           |--lpush to Redis queue---->|
   |                           |                           |
   |<--{type: "status",        |                           |
   |    block_idx: 0,          |                           |
   |    status: "queued"}------|                           |
   |                           |                           |
   |                           |<--brpop, process----------|
   |                           |                           |
   |                           |<--pubsub: done------------|
   |                           |                           |
   |<--{type: "status",        |                           |
   |    block_idx: 0,          |                           |
   |    status: "cached",      |                           |
   |    audio_url: "/v1/audio/hash"}                       |
   |                           |                           |
   |--GET /v1/audio/hash------>|                           |
   |<--audio bytes-------------|                           |
```

**Key design decisions:**
- WS for control messages (status updates, eviction)
- HTTP for audio fetch (large binary, cacheable)
- Redis pubsub for worker → gateway notifications
- Queue per model: `tts:queue:kokoro`, `tts:queue:higgs`

**Block statuses:** `queued` → `processing` → `cached` | `skipped` | `error`
- `skipped`: Block has unsynthesizable content (special chars like `❯`). Backend sends this instead of caching empty audio. Frontend treats skipped as resolved in buffer counting and auto-advances during playback.

### Browser TTS Flow (Free Tier)

Browser mode bypasses WS entirely:
1. Frontend synthesizes locally with Kokoro.js (WASM/WebGPU)
2. Frontend calls `POST /v1/audio` to cache result
3. Audio available at `GET /v1/audio/{hash}` for cross-device access

Browser mode is always free (zero server cost, no usage metering).

### Document Processors (`yapit/gateway/processors/document/`)

| Processor | Purpose | Cost |
|-----------|---------|------|
| MarkitdownProcessor | PDF/DOCX/HTML → markdown | Free |
| MistralOCRProcessor | Image/PDF OCR via Mistral API | Metered (subscription limit) |

### Models (`yapit/gateway/domain_models.py`)

---

## Database Migrations (Alembic)

**Dev mode** (`DB_DROP_AND_RECREATE=1`):
- Tables dropped and recreated from SQLModel on every restart
- Alembic is bypassed
- Change models freely, restart, done

**Prod mode** (`DB_DROP_AND_RECREATE=0`):
- Runs `alembic upgrade head` on startup
- Applies migrations to evolve schema while preserving data

### Creating Migrations

```bash
# Requires postgres running (make dev-cpu or docker compose up)
make migration-new MSG="add user preferences"
```

What this does:
1. Wipes database
2. Applies existing migrations (DB at "prod state")
3. Runs autogenerate (compares prod state to current models)
4. Generates migration with the diff

After running, restart dev (`make dev-cpu`) to recreate tables.

### Workflow for Schema Changes

1. Change models in code
2. Restart dev, test (create_all handles it)
3. When ready: `make migration-new MSG="description"`
4. Review generated migration in `yapit/gateway/migrations/versions/`
5. Commit model changes + migration together


### Gotcha: Stack Auth Tables

Alembic's `include_object` filter ignores Stack Auth tables (shared database). Only yapit-prefixed tables are managed.

### Resetting Prod DB (Pre-Launch)

While there are no real users, you can wipe yapit tables without touching Stack Auth:

```bash
ssh root@78.46.242.1
docker exec <postgres-container> psql -U yapit -d yapit -c "
DROP TABLE IF EXISTS blockvariants, blocks, documents, plans, usersubscriptions, usageperiods, ttsmodels, voices, alembic_version CASCADE;
"
```

Then redeploy - alembic runs migrations on empty tables. Stack Auth project/users stay intact.

### Migration Safety (Nice to Have)

**Current gap**: Dev mode (`DB_DROP_AND_RECREATE=1`) uses `create_all()`, bypassing migrations entirely. A broken migration passes dev/tests but fails in prod.

**Implemented**: `make migration-new` auto-fixes known issues and tests the migration immediately after generation.

**Future improvements**:
1. **Pre-deploy DB test** — Restore a prod backup locally, run migration against real data. Catches "works on empty DB, fails on prod data" issues. Ad-hoc, run before risky migrations.
2. **Rollback plan** — Document the rollback procedure for migrations. Requires migrations to be reversible (downgrade works). Test downgrade path for complex migrations.

---

## Design Decisions & Scope

**Core philosophy**: Accurate voicing of source content
- We read content as-is, not transform/summarize/rewrite
- Skip non-readable content (multi-line equations, code blocks) rather than LLM-translate
- "Do one thing well" - accurate TTS of documents

**OCR quality (Mistral)**: Currently 80-20 quality vs cost trade-off
- Mistral OCR is fast and cheap but not perfect
- Math detection inconsistent (some inline, some not)
- Heavy math papers aren't great TTS candidates anyway -> But see [[llm-preprocessing-prompt]] for fix.

---

## Running the Project

```bash
# Setup
uv sync --all-extras
echo "RUNPOD_API_KEY=xxx\nMISTRAL_API_KEY=xxx" > .env

# Start backend (PostgreSQL + Redis + Gateway)
make dev-cpu  # or make dev-mac

# Start frontend
cd frontend && npm run dev

# Test
make test-local

# Login at http://localhost/auth/signin with test user (credentials printed by dev-cpu)
```

---

## Known Issues & Tech Debt

### Medium Priority
- Improve UI for subscription limits (usage exceeded, upgrade prompts, greying out voices user can't access, etc.)
- **Filter system** mostly dead code? - either remove or implement filter toggles for some things like skipping urls or whatever if it is needed

### Frontend Tech Debt (Refactoring Opportunities) [most of these bullets are prlly state - need to revisit]
- **API Provider complexity** - The `useRef` + interceptors pattern in `api.tsx` works but is convoluted. Could consider a `useAuthenticatedApi()` hook that handles async token fetch more elegantly.
- **unifiedInput.tsx growing** - Multiple modes (idle/text/url/file) and states getting complex. Could extract into composable hooks (useUrlMode, useFileMode, etc.) if it grows further.
- **Inconsistent API call patterns** - Some components check `isAuthReady`, some don't need to. Pattern could be standardized with a wrapper hook that handles waiting internally.
- **Dropdown+dialog state coordination** - The pattern of closing dropdown before opening dialog (sidebar rename) is easy to forget and caused a freeze bug. Consider a utility or clearer pattern.
- **No global document state** - Sidebar fetches documents independently. Fine for now, but if multiple components need document list, would need refetch or context.

## Quick todo list 

- can we parse footnotes from text from html/markdown? example from here: https://whatisintelligence.antikythera.org/chapter-01/#

