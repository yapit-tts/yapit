# Mermaid Diagram Proposals

Side-by-side comparison isn't practical in markdown, so each section shows the
proposed Mermaid version with notes on what it replaces and what's improved.

These use: `sequenceDiagram` (lifecycle flows), `flowchart` (decision trees,
pipelines), and flowchart subgraphs (architecture). All render natively on GitHub.

---

## 1. Synthesis Lifecycle

**Replaces:** `architecture.md` lines 116-157 (ASCII sequence diagram)

**Improvements:** Autonumbered messages, activation bars show processing time,
`alt` blocks for cache/inflight/new branching, `Note` for inline context,
`box` groups participants by role. The ASCII version had all this as
free-form text annotations that were hard to follow.

**Accuracy fix:** Added subscriber notification step before DB update (matches
actual code order in `result_consumer.py`).

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

    Browser->>Gateway: synthesize {block_indices, model, voice, cursor}
    activate Gateway

    Note over Gateway: For each block:<br/>variant_hash = sha256(text+model+voice+params)

    alt Cached (SQLite + Postgres)
        Gateway-->>Browser: status: cached + audio_url
    else Already in-flight
        Note over Gateway: Subscribe to variant_hash
        Gateway-->>Browser: status: queued
    else New job
        Gateway->>Redis: SET inflight key (NX)<br/>ZADD tts:queue:{model}
        Gateway-->>Browser: status: queued
    end
    deactivate Gateway

    Worker->>Redis: BZPOPMIN tts:queue:{model}
    activate Worker
    Note over Worker: Synthesize audio<br/>(Kokoro or Inworld API)
    Worker->>Redis: LPUSH tts:results
    deactivate Worker

    activate Gateway
    Note over Gateway: Result consumer (BRPOP)
    Gateway->>Redis: DELETE inflight key (first wins)

    alt Duplicate result
        Note over Gateway: DELETE returned 0 → skip
    else Empty audio
        Gateway-->>Browser: status: skipped
    else Success
        Gateway->>Gateway: Write audio to SQLite cache
        Gateway-->>Browser: status: cached + audio_url
        Note over Gateway: PUBLISH → pubsub → WebSocket
        Gateway->>Gateway: UPDATE BlockVariant
        Gateway->>Gateway: Record usage (chars × multiplier)
    end
    deactivate Gateway

    Browser->>Gateway: GET /v1/audio/{hash}
    Gateway-->>Browser: audio/ogg bytes
```


## 2. Document AI Extraction (non-batch)

**Replaces:** `architecture.md` lines 162-199 (ASCII sequence diagram)

Shows the Gemini-based extraction flow for PDFs/images. This is the
*non-batch* path — batch mode submits all pages to the Gemini Batch API
instead, with a background poller checking for completion (50% cost
reduction).

**Improvements:** `loop` for polling, `par` for per-page parallelism,
activation bars, proper branching with `alt`. The ASCII version used
`─ ─ ─(async)─ ─ ─` freehand annotation to show async behavior — Mermaid
makes this structural.

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
        Note over External: Render page, run DocLayout-YOLO,<br/>crop figures, store images
        External-->>Gateway: figure URLs
        Gateway->>External: Gemini API (page PDF + figure prompt)
        External-->>Gateway: markdown with placeholders
        Note over Gateway: Substitute placeholders → image URLs<br/>Cache: content_hash:processor:version:page
    end
    deactivate Gateway

    loop Poll until complete
        Browser->>Gateway: POST /extraction/status
        alt Still processing
            Gateway-->>Browser: {completed: [0,1,3], status: "processing"}
        else All pages done
            activate Gateway
            Note over Gateway: Parse markdown → transform → blocks → Postgres
            Gateway-->>Browser: {status: "complete", document_id}
            deactivate Gateway
        end
    end
```


## 3. Per-Block Synthesis Flow

**Replaces:** `tts-pipeline.md` lines 62-88 (ASCII flowchart)

**Improvements:** Decision diamonds render cleanly without manual box-drawing.
The ASCII version needed careful column alignment for every branch.
Added subscriber tracking step (matches actual code order).

```mermaid
flowchart TD
    A["Compute variant_hash<br/>sha256(text + model + voice + params)"] --> B{"Cached?<br/>(SQLite data + Postgres variant)"}
    B -->|Yes| C["Return <b>cached</b> + audio_url"]
    B -->|No| D{"Usage limit<br/>exceeded?"}
    D -->|Over limit| E["Return <b>error</b>"]
    D -->|OK| F["Track subscriber<br/>(if WebSocket)"]
    F --> G{"Inflight key<br/>exists?"}
    G -->|Yes| H["Already processing →<br/>return <b>queued</b>"]
    G -->|No| I["SET inflight key (NX)<br/>Create BlockVariant<br/>ZADD tts:queue:{model}"]
    I --> J["Return <b>queued</b>"]
```


## 4. Input Paths

**Replaces:** `document-processing.md` lines 12-39 (ASCII flowchart)

**Improvements:** Three entry points converging is natural for flowcharts.
The ASCII version had careful column alignment for three parallel paths
that broke on edits. Mermaid handles the layout automatically.

**Accuracy fix:** arXiv detection happens in *both* the website and document
paths. `/website` calls `extract_website_content()` which checks
`detect_arxiv_url()`. `/document` also checks for arXiv URLs (when
`ai_transform=false`). Both route to the Markxiv sidecar.

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


## 5. Website Extraction

**Replaces:** `document-processing.md` lines 49-62 (ASCII tree)

**Improvements:** Decision branches with fallback paths. The ASCII version
was a pseudo-tree with `├──` and `└──` that couldn't show the full flow
without getting unwieldy.

```mermaid
flowchart TD
    URL["URL"] --> AX{"arXiv?<br/>(arxiv.org, alphaxiv, ar5iv)"}
    AX -->|Yes| MX["Markxiv sidecar<br/>LaTeX source → pandoc → markdown"]
    AX -->|No| DL["Download HTML via httpx<br/>(through Smokescreen SSRF proxy)"]
    DL --> TRAF["Extract with trafilatura"]
    TRAF --> EMPTY{"Extraction<br/>empty?"}
    EMPTY -->|Yes| FALLBACK["MarkItDown fallback"]
    EMPTY -->|No| JS{"JS-rendered page?<br/>(React/Vue patterns, or<br/>large HTML → tiny markdown)"}
    JS -->|Yes| PW["Playwright render<br/>(browser pool, semaphore=100)"]
    PW --> RESOLVE
    JS -->|No| RESOLVE["Resolve relative URLs<br/>to absolute"]
    FALLBACK --> RESOLVE
```


## 6. PDF/Image Extraction Pipeline

**Replaces:** `document-processing.md` lines 83-102 (ASCII tree)

**Improvements:** Shows the parallel nature (YOLO + page extraction happen
concurrently via `asyncio.as_completed`). The ASCII version was strictly
sequential which misrepresented the actual flow.

```mermaid
flowchart TD
    PDF["PDF bytes"] --> PAGES["Extract per-page PDFs<br/>(pymupdf)"]

    PAGES --> YOLO["YOLO figure detection<br/>(queue → worker)"]
    YOLO --> CROPS["Crop figures, store images<br/>(local FS or Cloudflare R2)"]

    PAGES --> PROMPT["Build Gemini prompt<br/>with figure placeholders"]
    CROPS --> PROMPT

    PROMPT --> GEMINI["Send page PDF + prompt<br/>to Gemini API"]
    GEMINI --> SUB["Substitute placeholders<br/>→ actual image URLs"]
    SUB --> CACHE["Cache per page<br/>content_hash:processor:version:page_idx"]

    style YOLO fill:#4a3728
    style GEMINI fill:#283748
```


## 7. Result Consumer

**Replaces:** `tts-pipeline.md` lines 165-178 (ASCII tree)

**Improvements:** Shows the branching clearly. The ASCII version used
`├──` tree notation with inline steps that mixed control flow and data flow.

**Accuracy fix:** Notification happens before DB update in actual code.

```mermaid
flowchart TD
    BRPOP["BRPOP tts:results"] --> CLAIM["DELETE inflight key<br/>(atomic, first deleter wins)"]
    CLAIM --> DUP{"DELETE<br/>returned 0?"}
    DUP -->|Yes| SKIP_DUP["Skip — already finalized"]
    DUP -->|No| CHECK{"Result type?"}
    CHECK -->|Error| ERR["Notify subscribers with error"]
    CHECK -->|Empty audio| SKIP["Notify: <b>skipped</b><br/>(whitespace-only blocks)"]
    CHECK -->|Success| S1["Decode base64 → SQLite cache"]
    S1 --> S2["PUBLISH notification<br/>(pubsub → WebSocket → client)"]
    S2 --> S3["UPDATE BlockVariant<br/>(duration_ms, cache_ref)"]
    S3 --> S4["Record usage<br/>(chars × model multiplier)"]
```


## 8. Visibility + Overflow Scanners

**Replaces:** `tts-pipeline.md` lines 193-207 (two small ASCII trees)

**Improvements:** Combined into one diagram showing both reliability
mechanisms and how they feed back into the queue.

```mermaid
flowchart TD
    subgraph vis ["Visibility Scanner (every 15s)"]
        VS["Scan tts:processing:*<br/>for jobs > timeout"]
        VS --> RETRY{"retries < max?"}
        RETRY -->|Yes| REQUEUE["Re-queue with<br/>retry_count++"]
        RETRY -->|No| DLQ["Dead letter queue<br/>(TTL 7 days)"]
        DLQ --> ERRSUB["Push error result<br/>for subscriber notification"]
    end

    subgraph overflow ["Overflow Scanner (every 5s)"]
        OS["ZRANGEBYSCORE for<br/>jobs waiting > threshold"]
        OS --> RP["Remove from local queue<br/>Submit to RunPod serverless"]
        RP --> POLL["Poll for completion"]
        POLL --> RESULT["Push to tts:results<br/>(same path as local workers)"]
    end
```


## 9. System Architecture

**Replaces:** `architecture.md` lines 11-60 (big ASCII box diagram)

The core insight: follow the request path top-to-bottom instead of trying
to spatially contain everything. Fewer subgraphs, let the flow direction
convey hierarchy. RunPod and external APIs are outside the swarm boundary.

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
            BG["Background tasks<br/>(result consumer, dispatchers, scanners)"]
        end

        GW --> PG[(Postgres)] & Redis[(Redis)] & SQLite[(SQLite Caches)]
        GW --> TS[(TimescaleDB)]

        GW --> Smoke["Smokescreen (SSRF proxy)"]
        GW --> Markxiv["Markxiv (arXiv)"]

        Redis -->|pull jobs| Kokoro["Kokoro TTS Workers"]
        Redis -->|pull jobs| YOLO["YOLO Figure Workers"]
    end

    Gemini["Gemini API"] ~~~ Inworld["Inworld API"] ~~~ Stripe

    GW <-->|extraction| Gemini
    GW <-->|premium TTS| Inworld
    GW <-->|billing| Stripe
    Kokoro -.->|overflow| RunPod["RunPod Serverless"]
```

Kokoro and YOLO are separate containers that pull directly from Redis
(`BZPOPMIN`). Inworld dispatchers also use Redis queues but live *inside*
the gateway (listed under "Background tasks") — they pull from
`tts:queue:inworld-*` and POST to the external API. So all worker paths
go through Redis, but only Kokoro/YOLO show a direct Redis edge because
they're the only ones with Redis as their sole interface.


## 10. Block Splitting

**Replaces:** `document-processing.md` lines 159-166 (ASCII tree)

```mermaid
flowchart TD
    A{"text > max_block_chars?"} -->|No| DONE["Single AudioChunk"]
    A -->|Yes| B["Split at sentence boundaries<br/>(. ! ?)"]
    B --> C{"Still too long?"}
    C -->|No| DONE2["Multiple AudioChunks<br/>with consecutive audio_block_idx"]
    C -->|Yes| D["Split at clause boundaries<br/>(, — : ;)"]
    D --> E{"Still too long?"}
    E -->|No| DONE2
    E -->|Yes| F["Split at word boundaries<br/>(last resort)"]
    F --> DONE2
```


## 11. TTS Pipeline Overview

**Replaces:** `tts-pipeline.md` lines 10-17 (ASCII box chain)

```mermaid
flowchart LR
    A["Document blocks<br/><i>text + audio_idx</i>"] --> B["WebSocket handler<br/><i>dedup + enqueue</i>"]
    B --> C["Redis queue<br/><i>sorted set FIFO</i>"]
    C --> D["Worker<br/><i>pull + synthesize</i>"]
    D --> E["Result consumer<br/><i>cache + notify</i>"]
```

---

## Summary

| # | Diagram | Source | Mermaid type | Verdict |
|---|---------|--------|--------------|---------|
| 1 | Synthesis lifecycle | architecture.md | sequenceDiagram | Clear win — activations, alt blocks, notes |
| 2 | AI extraction (non-batch) | architecture.md | sequenceDiagram | Clear win — loop, par, activation bars |
| 3 | Per-block synthesis | tts-pipeline.md | flowchart | Clear win — decision diamonds |
| 4 | Input paths | document-processing.md | flowchart | Clear win — 3 converging paths |
| 5 | Website extraction | document-processing.md | flowchart | Clear win — fallback chains |
| 6 | PDF extraction | document-processing.md | flowchart | Better — shows parallelism |
| 7 | Result consumer | tts-pipeline.md | flowchart | Better — clean branching |
| 8 | Scanners | tts-pipeline.md | flowchart | Better — combined + clearer |
| 9 | System architecture | architecture.md | architecture-beta | Try it — fallback to flowchart if unsupported |
| 10 | Block splitting | document-processing.md | flowchart | Clear win — cascading fallback |
| 11 | Pipeline overview | tts-pipeline.md | flowchart LR | Slight win — auto-aligned |

**Accuracy fixes applied:**
- Result consumer: notification before DB update (matches code)
- Per-block flow: subscriber tracking before inflight check
- Input paths: arXiv check shown in BOTH website and document paths (was only on document path)
- Document creation: renamed to "AI Extraction (non-batch)" — only covers Gemini path, not general creation
- System architecture: RunPod is CPU serverless, not GPU overflow
- Website extraction: trafilatura emptiness check triggers MarkItDown fallback (was underspecified)
