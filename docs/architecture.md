# Yapit Architecture

## System Overview

```mermaid
flowchart TD
    CF["Cloudflare (CDN, R2)"] --> Traefik

    subgraph swarm ["Docker Swarm"]
        Traefik["Traefik (TLS)"] --> Frontend["Frontend · React SPA · Nginx"]
        Traefik --> GW

        Auth["Stack Auth"] -.->|tokens| GW

        subgraph GW ["Gateway (FastAPI)"]
            direction LR
            API["REST API · WebSocket"]
            BG["Background tasks<br/>(consumers, dispatchers, scanners)"]
        end

        GW --> PG[(Postgres)] & Redis[(Redis)] & SQLite[(SQLite Caches)]
        GW --> TS[(TimescaleDB)]

        GW --> Smoke["Smokescreen (SSRF proxy)"]
        GW --> Markxiv["Markxiv"]

        Redis -->|pull jobs| Kokoro["Kokoro TTS Workers"]
        Redis -->|pull jobs| YOLO["YOLO Figure Workers"]
    end

    Gemini["Gemini API"] ~~~ Inworld["Inworld API"] ~~~ Stripe

    GW <-->|extraction| Gemini
    GW <-->|premium TTS| Inworld
    GW <-->|billing| Stripe
    Kokoro -.->|overflow| RunPod["RunPod Serverless"]
```

**Gateway** is a FastAPI process handling all HTTP/WebSocket traffic plus
background tasks (result consumer, billing consumer, cache persister,
Inworld dispatchers, visibility/overflow scanners). Only service with
Postgres access.

**Workers** pull jobs from Redis queues and push results back. The gateway
never pushes to workers directly — any machine with Redis access can be a
worker. Kokoro and YOLO run as separate containers. Inworld dispatchers run
inside the gateway (just HTTP calls).

**Storage:**

| Store | Role |
|-------|------|
| Redis | Job queues, inflight tracking, pubsub, audio hot cache (300s TTL) |
| SQLite | Audio cold cache (persistent, LRU-evicted), document cache, extraction cache |
| Postgres | Documents, blocks, variants, billing, user data |
| TimescaleDB | Metrics and events |


## Document Processing

### Input paths

Content enters as URLs, file uploads, or raw text. All paths produce markdown.

```mermaid
flowchart TD
    T["Text input"] --> TEXT["POST /text"]
    U["URL input"] --> P1["POST /prepare<br/>Download + cache by URL hash"]
    F["File upload"] --> P2["POST /prepare/upload<br/>Cache by content hash"]

    P1 & P2 --> META["Return hash + metadata<br/>(page count, title, cost estimate)"]

    META --> W{"Content type?"}
    W -->|HTML| WS_AX{"arXiv URL?"}
    WS_AX -->|Yes| MX["Markxiv sidecar<br/>(LaTeX → markdown)"]
    WS_AX -->|No| WS["POST /website<br/>(trafilatura + fallbacks)"]

    W -->|PDF / image| DOC_AX{"arXiv URL?<br/>(and not ai_transform)"}
    DOC_AX -->|Yes| MX
    DOC_AX -->|No| AI{"AI extraction?"}
    AI -->|Yes| GEM["Gemini<br/>(vision-based, paid)"]
    AI -->|No| MIT["MarkItDown<br/>(free, simple)"]

    TEXT & WS & MX & GEM & MIT --> MD["Markdown"]
    MD --> PARSE["Parse + Transform → blocks"]
```

Document creation is two steps: `/prepare` downloads and caches content,
returning metadata (page count, title, cost estimate). The frontend shows
this to the user, then calls the create endpoint with the cache key.

### Website extraction

```mermaid
flowchart TD
    URL["URL"] --> AX{"arXiv?<br/>(arxiv.org, alphaxiv, ar5iv)"}
    AX -->|Yes| MX["Markxiv sidecar<br/>LaTeX source → pandoc → markdown"]
    AX -->|No| DL["Download HTML via httpx<br/>(through Smokescreen SSRF proxy)"]
    DL --> TRAF["Extract with trafilatura"]
    TRAF --> EMPTY{"Extraction<br/>empty?"}
    EMPTY -->|Yes| FALLBACK["MarkItDown fallback"]
    EMPTY -->|No| JS{"JS-rendered page?<br/>(React/Vue patterns, or<br/>large HTML → tiny markdown)"}
    JS -->|Yes| PW["Playwright render<br/>(browser pool)"]
    PW --> RESOLVE
    JS -->|No| RESOLVE["Resolve relative URLs<br/>to absolute"]
    FALLBACK --> RESOLVE
```

### AI extraction

Gemini vision-based extraction for PDFs and images. Pages are processed in
parallel, cached per-page — re-extracting a 100-page PDF where 3 pages
changed only re-processes those 3. YOLO figure detection runs first to
identify charts, diagrams, and figures that PyMuPDF can't extract.

```mermaid
sequenceDiagram
    autonumber

    participant Browser
    participant Gateway
    participant External

    Browser->>Gateway: POST /prepare {url}
    activate Gateway
    Gateway->>External: Download via httpx (through Smokescreen)
    External-->>Gateway: content
    Note over Gateway: Cache by URL hash
    Gateway-->>Browser: {hash, metadata, uncached_pages}
    deactivate Gateway

    Note over Browser: Show page count, title,<br/>estimated extraction cost

    Browser->>Gateway: POST /document {hash, ai_transform=true}
    activate Gateway
    Gateway-->>Browser: 202 Accepted {extraction_id}

    par Per-page (asyncio.as_completed)
        Gateway->>External: YOLO figure detection (queue → worker)
        External-->>Gateway: figure URLs
        Gateway->>External: Gemini API (page PDF + figures)
        External-->>Gateway: markdown
        Note over Gateway: Cache per page
    end
    deactivate Gateway

    loop Poll until complete
        Browser->>Gateway: POST /extraction/status
        alt Still processing
            Gateway-->>Browser: {completed: [0,1,3], status: "processing"}
        else All pages done
            activate Gateway
            Note over Gateway: Parse markdown → blocks → Postgres
            Gateway-->>Browser: {status: "complete", document_id}
            deactivate Gateway
        end
    end
```

Batch mode submits all pages to the Gemini Batch API instead (50% cost
reduction), with a background poller checking for completion.

### Markdown → blocks

Parsed by markdown-it-py (CommonMark + extensions). The transformer walks
the AST and produces typed blocks with HTML for display and audio chunks
for TTS. Speakable block types: heading, paragraph, list, blockquote,
image captions, footnotes. Non-speakable: code, math, tables.

Custom HTML tags route content between display and speech:
`<yap-show>` (display only), `<yap-speak>` (TTS only),
`<yap-cap>` (image captions, both). Long blocks are split at sentence →
clause → word boundaries to keep synthesis chunks short.


## TTS Pipeline

Two synthesis paths, same interface:
- **Server**: WebSocket → Redis queue → worker → result consumer → cached audio over HTTP
- **Browser**: Kokoro.js in a Web Worker (WASM/WebGPU). Audio stays in memory. Free, private, Kokoro-only.

### Synthesis lifecycle

```mermaid
sequenceDiagram
    autonumber

    box Client
        participant Browser
    end
    box Backend
        participant Gateway
        participant Redis
    end
    box Workers
        participant Worker
    end

    Browser->>Gateway: synthesize {block_indices, model, voice}
    activate Gateway

    Note over Gateway: For each block:<br/>variant_hash = hash(text + model + voice + params)

    alt Cached (Redis or SQLite)
        Gateway-->>Browser: status: cached + audio_url
    else Already in-flight
        Note over Gateway: Subscribe to existing job
        Gateway-->>Browser: status: queued
    else New job
        Gateway->>Redis: Queue job
        Gateway-->>Browser: status: queued
    end
    deactivate Gateway

    Worker->>Redis: Pull job from queue
    activate Worker
    Note over Worker: Synthesize audio<br/>(Kokoro local or Inworld API)
    Worker->>Redis: Push result
    deactivate Worker

    activate Gateway
    Note over Gateway: Result consumer picks up result

    alt Success
        Gateway->>Redis: SET audio (hot cache, 300s TTL)
        Gateway-->>Browser: status: cached + audio_url
        Note over Gateway: Push billing event (async)
        Note over Gateway: Push persist event (async)
    else Error / Empty
        Gateway-->>Browser: status: error or skipped
    end
    deactivate Gateway

    Note over Gateway: Cache persister: batch-write<br/>Redis audio → SQLite (background)

    Browser->>Gateway: GET /v1/audio/{hash}
    Note over Gateway: Redis first → SQLite fallback
    Gateway-->>Browser: audio/ogg bytes
```

### Result processing

Three isolated consumers process results in parallel:

```mermaid
flowchart LR
    RES["tts:results"] --> RC["Result consumer<br/><b>hot path</b>"]
    RC --> REDIS_SET["Redis SET audio<br/>(sub-ms)"]
    REDIS_SET --> NOTIFY["Notify client<br/>(pubsub → WS)"]
    NOTIFY --> BILL["Push to<br/>tts:billing"]
    NOTIFY --> PERSIST["Push to<br/>tts:persist"]

    BILL --> BC["Billing consumer<br/><b>cold path</b>"]
    BC --> PG[(Postgres<br/>usage + metadata)]

    PERSIST --> CP["Cache persister<br/><b>batch writes</b>"]
    CP --> SQLite[(SQLite<br/>cold cache)]
```

- **Result consumer** (hot path): Redis SET + notify. No disk I/O. Sub-ms.
- **Billing consumer**: Drain-on-wake batching. Own Postgres pool, can never starve the request path.
- **Cache persister**: Drain-on-wake batching. N rows in one SQLite transaction = one fsync instead of N.

### Workers

**Kokoro** (local model): Sequential processing, one job per replica. Runs
in its own container. Replica count scales with CPU cores.

**Inworld** (API model): Parallel dispatching inside the gateway. One async
task per job, unlimited concurrency.

### Reliability

```mermaid
flowchart TD
    subgraph vis ["Visibility Scanner"]
        VS["Detect stuck jobs<br/>(processing > timeout)"]
        VS --> RETRY{"Retries left?"}
        RETRY -->|Yes| REQUEUE["Re-queue"]
        RETRY -->|No| DLQ["Dead letter queue"]
        DLQ --> ERRSUB["Notify subscribers<br/>of failure"]
    end

    subgraph overflow ["Overflow Scanner"]
        OS["Detect queue backlog<br/>(waiting > threshold)"]
        OS --> RP["Offload to<br/>RunPod serverless"]
        RP --> RESULT["Results return via<br/>same tts:results path"]
    end
```

### Frontend playback

State machine decoupled from React, bridged via `useSyncExternalStore`.
Prefetches 8 blocks ahead. Audio and synthesis are injected dependencies —
the engine doesn't know if audio came from server or browser synthesis.

Server synthesizer batches per-block calls into a single WebSocket message.
Audio playback uses `HTMLAudioElement` directly (not Web Audio API) because
`AudioBufferSourceNode.playbackRate` changes pitch with speed.


## Key Design Decisions

**Pull-based workers**: Workers pull from Redis queues. Faster workers
naturally pull more. Any machine with Redis access can be a worker. The
gateway doesn't need to know how many workers exist.

**Content-addressed cache**: Audio keyed by `hash(text + model + voice + params)`,
not by document or user. Two users reading the same article with the same
voice share cached audio.

**Redis-first audio serving**: Recently synthesized audio is served from
Redis (sub-ms). SQLite is the durable cold cache. The cache persister
batch-writes in the background — one fsync per batch instead of per row.

**Three-path result processing**: Hot path (Redis + notify) has zero disk
I/O. Billing and cache persistence run independently with their own
resources. No path can starve another.

**Duplicate prevention**: Inflight keys are atomically deleted at the start
of result processing. If a job completes twice (original + retry), only the
first to delete the key proceeds.

**Prepare/create split**: Document creation is two API calls. `/prepare`
downloads and caches content, returns metadata. The create endpoint uses
the cache key. Frontend shows costs before starting extraction.


## Deployment

Docker Compose with layered overrides:

```
docker-compose.yml              Base: all services + worker definitions
  └── docker-compose.dev.yml    Dev: host ports, volume mounts, stripe-cli
  └── docker-compose.prod.yml   Prod: Swarm mode, Traefik labels, ghcr.io images
```

Production runs on Docker Swarm (single node). CI/CD pushes to `main`
trigger lint, test, build, push to ghcr.io, SSH deploy, and health check.

Worker replica counts are configured via env vars. External workers connect
via Tailscale VPN.
