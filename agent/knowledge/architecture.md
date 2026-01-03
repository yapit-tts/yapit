
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
- **v1**: All essential features + billing/Stripe, ready for beta testers
- **v1.x**: add release workflow (main, dev), monitoring, admin panel, self-host docs
- **Ship**: Dogfooding complete, proper deploy pipeline (Hetzner + Cloudflare + RunPod?)

---

## Critical Distinction: MarkItDown vs Markdown Parser

These are TWO SEPARATE components:

### MarkItDown
**Purpose**: Converts documents TO markdown
**Input**: PDF, DOCX, HTML, etc.
**Output**: Markdown text string
**Location**: `yapit/gateway/processors/document/markitdown.py`
**Status**: ✅ Working
**Note**: Preserves URLs as-is (relative stays relative). We post-process with `_resolve_relative_urls()` in `documents.py` to resolve relative URLs and convert same-page anchors.

```
PDF/DOCX/HTML  →  MarkItDown  →  Markdown string
```

### Markdown Parser (PR #50)
**Purpose**: Parse markdown to understand structure for display and smart splitting
**Input**: Markdown string
**Output**: Structured document format (JSON with typed blocks)
**Location**: `yapit/gateway/processors/markdown/`
**Status**: ✅ IMPLEMENTED

```
Markdown string  →  parse_markdown()  →  AST  →  transform_to_document()  →  StructuredDocument JSON
```

**Block types**: heading, paragraph, list, blockquote, code, math, table, image, hr
**Audio mapping**: Prose blocks get `audio_block_idx: number`, non-prose (code/math/table) get `null`

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
├── Kokoro CPU worker (optional, for server-side free tier)
└── SQLite audio cache (local SSD)
         ↓
RunPod (serverless, on-demand)
└── GPU workers for premium models (HIGGS, etc.)
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

**Implementation:**
- LRU eviction with size cap (~20-50GB based on SSD budget)
- TTL: 7-14 days for untouched entries
- Loss tolerance: High (audio can be regenerated)

### Free Tier Strategy: Batch Conversion (todo this is outdated)

**Problem**: Browser TTS (Kokoro.js WASM) is slow and unreliable - some devices can't run WebGPU, inference takes 30s+ per block on CPU. But we want free tier to have zero marginal cost.

**Solution**: Offer Kokoro TTS for free with batch processing:
- User submits document, system queues all blocks for server-side Kokoro synthesis
- Processing happens on VPS CPU(s) in background - could take minutes to tens of minutes
- All blocks cached once complete - user gets notification, instant playback from cache
- Free users wait; paid users get instant playback via RunPod (priority queue)

**Trade-offs**:
- ✅ Zero marginal cost (VPS already paid for, just uses spare CPU cycles)
- ✅ More reliable than client-side WASM (server environment controlled)
- ✅ Works on all devices (no WebGPU requirement)
- ⚠️ Requires job queue system (Redis + worker process)
- ⚠️ UX for "come back later" needs thought (email notification? progress page?)
- ⚠️ VPS sizing affects queue depth - need to monitor

**Not yet implemented** - idea captured for future pricing/tier design.

---

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

### Key Models (`yapit/gateway/domain_models.py`)

- `Document` - Has `original_text`, `filtered_text`, `structured_content` (currently placeholder), `blocks`
- `Block` - Text chunk, ~10-20 sec audio, has `variants` (different voice/model combos)
- `BlockVariant` - Specific synthesis (hash-keyed), links to cached audio
- `TTSModel` - Model config (sample_rate, channels)
- `Voice` - Voice belonging to model, with parameters
- `Plan` - Subscription tier with usage limits (server_kokoro_characters, premium_voice_characters, ocr_pages)
- `UserSubscription` - Links user to plan, tracks Stripe subscription state and billing period
- `UsagePeriod` - Per-period usage counters, reset on subscription renewal

### Caching

- **Audio cache**: SQLite, keyed by variant hash (text + model + voice + codec + params)
- **Document cache**: SQLite, TTL-based, stores prepared documents before creation (TODO: what is this?)
- TODO OCR cache?
- TODO Cache vacuuming not done yet.

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

### Key Files

| File | Purpose |
|------|---------|
| `yapit/gateway/alembic.ini` | Alembic config |
| `yapit/gateway/migrations/env.py` | Imports models, filters to yapit tables only |
| `yapit/gateway/migrations/versions/` | Migration files |
| `yapit/gateway/db.py` | Runs alembic on startup in prod mode |

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

## Frontend Architecture

### Current State (main branch)

**Working:**
- `TextInputPage` → `TextInputForm` → POST /documents/text → navigate to PlaybackPage
- `PlaybackPage` - Block-by-block synthesis with Web Audio API
  - Browser TTS via Kokoro.js (WASM/WebGPU) or server-side via API
  - Prefetches next blocks while current plays
  - Duration correction (estimated vs actual)
  - Volume control via GainNode
  - PCM + encoded audio support
  - Pitch-preserving speed control (0.5x-3x) via native `preservesPitch`
  - Loading indicator during synthesis
  - Block click-to-jump with race condition handling
- Authentication via Stack-Auth
- Audio controls: play/pause, volume, progress bar, speed slider, skip forward/back
- Voice picker: Kokoro (28 voices) and HIGGS (2 voices) tabs, pinning, localStorage persistence
- Model source toggle: Browser (free, WASM) or Server (subscription, faster)
- Cancel synthesis: Hover spinner to reveal stop button
- Playback position memory: Resumes from last block per document (localStorage)
- MediaSession integration: Hardware media keys work and sync UI state

**Not Working / Incomplete:**
- Admin panel - Stub

### Recent: PR #49 - Unified Document Input

**Merged to dev 2025-12-16:**
- `unifiedInput.tsx` - Text/URL/file input with drag-n-drop, mode detection
- `metadataBanner.tsx` - Shows page count, credit cost, OCR toggle
- `useDebounce.ts` - Debounce hook for URL validation
- Sidebar now fetches from API (no longer mock data)

---

## Key Files Reference

### Backend
| File | Purpose |
|------|---------|
| `yapit/gateway/api/v1/documents.py` | Document CRUD, prepare flow, website stub |
| `yapit/gateway/api/v1/ws.py` | WebSocket endpoint for TTS synthesis control |
| `yapit/gateway/api/v1/audio.py` | Audio fetch (GET) and browser TTS submit (POST) |
| `yapit/gateway/processors/tts/manager.py` | TTSProcessorManager - routes model+mode to processor |
| `yapit/gateway/processors/tts/base.py` | BaseTTSProcessor - queue polling, pubsub publish |
| `yapit/gateway/processors/tts/local.py` | LocalProcessor - HTTP worker communication |
| `yapit/gateway/processors/tts/runpod.py` | RunpodProcessor - serverless API |
| `yapit/gateway/processors/document/markitdown.py` | MarkItDown wrapper |
| `yapit/gateway/domain_models.py` | All SQLModel definitions |
| `yapit/gateway/deps.py` | FastAPI dependency injection |
| `yapit/gateway/cache.py` | SQLite cache implementation |
| `yapit/contracts.py` | SynthesisJob, SynthesisResult, WS message schemas |
| `yapit/gateway/processors/markdown/parser.py` | markdown-it-py wrapper, parse_markdown() |
| `yapit/gateway/processors/markdown/transformer.py` | AST → StructuredDocument conversion |
| `yapit/gateway/processors/markdown/models.py` | Pydantic models for StructuredDocument |

### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/pages/PlaybackPage.tsx` | Audio playback, block management, document display |
| `frontend/src/lib/audio.ts` | AudioPlayer with Web Audio API, native pitch-preserving speed |
| `frontend/src/components/structuredDocument.tsx` | Block-type renderers, highlighting, click-to-jump |
| `frontend/src/components/soundControl.tsx` | Play/pause, volume, speed slider, progress |
| `frontend/src/api.tsx` | Axios instance with Stack-Auth |

### Config
| File | Purpose |
|------|---------|
| `tts_processors.dev.json` | Routes model+mode to processors (backend + optional overflow) |
| `document_processors.dev.json` | Maps processor slugs to classes |
| `.env.dev` | Dev environment variables |

---

## Roadmap

### ✅ v0 Complete
- Audio playback with play/pause, speed control (native preservesPitch), skip blocks
- Browser TTS (Kokoro.js) with anonymous sessions
- Markdown parsing, structured document display, block highlighting, click-to-jump
- Unified document input (text/URL/file), metadata preview

### v0.x In Progress
- Sidebar polish: header/branding, footer/user menu, document actions
- UX iteration based on dogfooding

### v1 (Later)
- ~~Cloud storage~~ - Not needed (text in Postgres, audio cache on local SSD)
- Admin frontend - Dashboard, settings
- ~~Billing - Stripe integration~~ ✅ Subscription system with Stripe Managed Payments
- Rate limiting - Not urgent until public launch
- Monitoring - See `monitoring-observability-logging.md` plan
- OAuth providers (GitHub, Google) - create OAuth apps, configure in Stack Auth dashboard

---

## Open Questions (For Future Implementation)

1. **Inline math handling**: Documents may have inline `$...$` LaTeX in paragraphs
   - Currently: raw LaTeX shows in prose, gets read by TTS (suboptimal)
   - Promptable TTS models (like HIGGS) can be instructed how to read equations
   - This becomes solvable when we add premium model support (v1)

---

## Design Decisions & Scope

**Core philosophy**: Accurate voicing of source content
- We read content as-is, not transform/summarize/rewrite
- Skip non-readable content (multi-line equations, code blocks) rather than LLM-translate
- "Do one thing well" - accurate TTS of documents

**OCR quality (Mistral)**: Currently 80-20 quality vs cost trade-off
- Mistral OCR is fast and cheap but not perfect
- Math detection inconsistent (some inline, some not)
- Heavy math papers aren't great TTS candidates anyway
- May evaluate alternatives for complex academic layouts

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
- **URL structure review** - Current `/playback/{id}` works but consider alternatives: `/d/{id}` (shorter), `/documents/{id}` (RESTful), or `/listen/{id}` (action-oriented). Low priority but worth thinking about before public launch.
- UI for subscription limits (usage exceeded, upgrade prompts, greying out voices user can't access, etc.)
- Instead of Browser/Server call it Local/Cloud or sth?

## This section is now todos

### Anonymous User Safeguards (Add When Needed)
No limits on anonymous users currently. Add config-driven safeguards based on real usage:
- Document limits (max per user), storage limits, auto-eviction after N days inactivity
- Account claiming flow (link anon-uuid to authenticated account)
- Implementation: Settings env vars (e.g., `ANON_MAX_DOCUMENTS`, `ANON_EVICTION_DAYS`)

### Frontend Tech Debt (Refactoring Opportunities)
- **API Provider complexity** - The `useRef` + interceptors pattern in `api.tsx` works but is convoluted. Could consider a `useAuthenticatedApi()` hook that handles async token fetch more elegantly.
- **unifiedInput.tsx growing** - Multiple modes (idle/text/url/file) and states getting complex. Could extract into composable hooks (useUrlMode, useFileMode, etc.) if it grows further.
- **Inconsistent API call patterns** - Some components check `isAuthReady`, some don't need to. Pattern could be standardized with a wrapper hook that handles waiting internally.
- **Dropdown+dialog state coordination** - The pattern of closing dropdown before opening dialog (sidebar rename) is easy to forget and caused a freeze bug. Consider a utility or clearer pattern.
- **No global document state** - Sidebar fetches documents independently. Fine for now, but if multiple components need document list, would need refetch or context.

### ~~Low Priority / Later~~ The actual, slightly random, todolist
- **Cloudflare optimizations**: Review speed/security features at https://dash.cloudflare.com/58e2a94a0efae64b19d2bec84af0700d/yapit.md/speed/optimization/recommendations - lots of options beyond the quick toggles (Page Rules, caching config, WAF rules, etc.)
- **Kokoro thread/replica tuning for prod**: Test T=8×2 vs T=4×4 on 16 vCPU. T=8×2 = lower latency per request; T=4×4 = better load distribution. Compare UX impact.
- **Filter system** (contracts.py) - Partially implemented, ignoring for now.
- **Admin panel** (#22, #25) - Stub - actually needed? E.g. for self-host, but what settings even?
- **Rate limiting** (#47) - Not urgent until public launch.
- **Cache eviction** — LRU + TTL mechanism not implemented yet. Low priority for beta (small user count), needed before scale.
- **RunPod overflow for Kokoro** — Currently no overflow endpoint configured. Add one, delete unused HIGGS endpoint. Storage cost ~few cents/month.
- Hetzner backups + scaling + restore drill (verify the flow works before going live)
- Auto-deploy webhook on merge to main
- Production seed script (one-time seed for fresh deployments)
- mistral ocr is 50% off with batch requests (which ususally are not much slower) (and you can send single requests as batch of 1 document). Question is how to UX this best... (because it *might* still lead to a delay and yh idk maybe we just give the choice but yk how to ui/ux this).
- backup strategy. rsync.net?
- this text maybe doesnt belong here but I want to write downt he thought:
  - so we decided we don'T need aws or sth for audio cache since it's ephemeral and not too large (hetzner with bigger ssd shouldbe fine)
  - same thing for transformed documents (just md, even smaller)all-extras
  - but what about mistral ocr? with mistral ocr 3 (no choice to stay at 2), the price is now 2x, landing at 2$/1k pages. 
  - that's where the original thoughts of like having a cache for stuff like that came from.
  - because for OCR it literally makes sense. well, for documents that are frequently read again. so like we could offer a free selection too... like yk periodically indexing archive.
  - or like hm could make an exception for arxiv and yk only save arxiv pdfs... but idk how we'd implement that best.
  - or idk yh how to integrate with freemium.
  - or whether it's worth in general to like have a cache for ocred content.
  - wait -- since we store the ocr'd text (transformed document) in the db as part of the document model, we already have a cache for that, right? so we only need to make sure we don't re-ocr sth we already ocred! (unless msitral releases a bette rmodel again in which case we'd evict / relax that check -- but then we'd need to track the model version used for ocr per document - doable. currently it's just "mistral-ocr" bcs they auto-update. but yh we could like add an env var which we update)
- also need to try updating the block size to say 200 or 250, and before that try better splitting algorithms already, taking into account that it's better to split at a "," in adition to "?!. ", and that being able to split at such a point is better than reaching excactly the limit. (so like a soft limit with preferred split points)
 - because yh smtms it's not the best flow still yk if the sentences are kinda split audibly unnaturally.
 - i would however do this end-to-end, after we've test-deployed on the VPS, so we see how fast the real kokoro cpu inference is. + testing a bit more with laptops that actually have a functioning webgpu...
 - stress test document sidebar with 500+ documents (pagination working, implemented in FE, etc.?)
- ~~Dokploy~~ - using it, see [[dokploy-operations]]
- write a testimonial for "VibeTyper" The S2T software I use (the dev will give a backlink to yapit / + my personal site and test the product too - plus he said he uses dockploy for VibeTyper)
- is the edge case of a block being sent to a server worker which for some reason fails to process it (worker crash / oom / whatever) handled properly? like is there a timeout after which we retry or sth? or do we just hang forever?
- make the app responsive, even with the 1.8k pages rationality A to Z endboss book (62h of audio) - clicking on it in the sidebar has noticeable delay. Else it seems to work well?
- convert guest user to registered user flow (when they sign up)!
- proper error msg / UI for 402s
- increase hitbox/size of "star" button for voices
- don't show languages other than the supported ones (english) for the kokoro local (WASM/WebGPU) model.
- tooltip on the sidbar for /subscriptonns: if rounding of usage -> ~0 show instead "<1" to be less confusing
- displaying hours in the /subcription (and sidebar pbar + tooltip) is kinda stupid. as if we think our users can't understand what chars are. But also like it's fundamentally stupid since it changes by up to 4x depending on your speed + max model or not... so if you listen 2x speed with max you'll have 5 hours on the plus plan instead of the advertised 20hours... nahbro. Should improve this.


### Nice to Have / Future Enhancements
- **Cross-device position sync**: Current position memory is localStorage only. Could add backend sync for resume across devices.
- **ArXiv URL first-class support**: Detect ArXiv URLs and fetch paper title via ArXiv API
- **Full document audio download**: Batch synthesis entire document to single audio file (MP3/WAV) for offline listening
- **Math-to-Speech for TTS**: Currently inline math is skipped for TTS. Options to consider:
  - Speech Rule Engine (SRE) / MathJax accessibility - converts MathML → speech strings
  - MathCAT - Rust-based alternative to SRE
  - LLM transcription - use cheap model to convert LaTeX → readable text (more flexible, natural-sounding)
  - Decision: Keep skipped for now, may revisit with LLM approach later
- Vim-style keybindings for playback control (space/play/pause, j/k skip blocks, h/l speed up/down, sth to go to start/end, sth to create new doc, etc.)
- being able to open things in/from the sidebar in a new tip tab (right click -> open in new tab on document in sidebar; should also work with control click and so on)
- when uploading a file, doc title could be prefilled from file name?
- web agent that better fetches some images (https://www.anthropic.com/engineering/writing-tools-for-agents - here some graphs are not loaded for example) [the url of one of those images: https://www.anthropic.com/_next/image?url=https%3A%2F%2Fwww-cdn.anthropic.com%2Fimages%2F4zrzovbb%2Fwebsite%2Fcdc027ad2730e4732168bb198fc9363678544f99-1920x1080.png&w=1920&q=75]
- clicking on the document title (when document is loaded), the behavior is a bit unintuitive? like a normal click opens in a new tab. but standard behaviorr is ctrl + click = open in new tab, normal click = open in same tab. so maybe we should change that?
- can we use audio gestures (on headphones) to control stepping back / forth in addition to play/pause? Are there standard events for that in the web audio api?
