---
status: done
refs: [38249e2]
started: 2026-02-04
---

# Task: Create Public-Facing Architecture Documentation

## Intent

Create a `docs/` directory with polished ASCII art diagrams and prose explaining Yapit's architecture for self-hosters and curious developers. Not API docs — system-level "how it works" documentation.

## Style

ASCII art diagrams throughout. No Mermaid, no image exports, no build tools. Two diagram types:

**Component/flow diagrams** — boxes, arrows, decision points:
```
┌─────────────┐     ┌ ─ ─ ─ ─ ─ ┐
│ Solid box   │     │ Dashed =    │    (optional/conditional)
│ = component │       external
└─────────────┘     └ ─ ─ ─ ─ ─ ┘

╔═══════════════╗
║ Double-line   ║    (major system boundary)
╚═══════════════╝

───▶  flow       - - ▶ optional/async       ◀───▶ bidirectional
```

**Sequence/interaction diagrams** — multi-actor timelines:
```
 Browser              Gateway              Redis
    │                    │                    │
    │  POST /prepare     │                    │
    │───────────────────▶│                    │
    │                    │  store cached doc  │
    │                    │───────────────────▶│
```

Prose should be external-audience friendly — no internal jargon, explain concepts from scratch. The `agent/knowledge/` files are the source material but need rewriting for public consumption.

## Scope

Documents to create (one per major flow):

- **Architecture overview** — high-level system diagram, services, how they connect
- **Document processing** — input paths, website vs document, markxiv, extraction, caching layers
- **TTS pipeline** — WebSocket protocol, Redis queues, workers, audio caching
- **Deployment** — Docker compose structure, configuration, self-hosting guide

Sequence diagrams for key interactions:
- PDF upload → extraction → document creation
- TTS WebSocket lifecycle
- Auth token flow
- Stripe webhook handling (if relevant for self-hosters)

## Assumptions

- Deferred until post-launch (code needs to stabilize first)
- Lives in `docs/` at repo root
- Markdown files only, no build step
- Target audience: technical users comfortable reading architecture docs

## Sources

**Knowledge files:**
- [[document-processing]] — primary source for doc processing flow
- [[tts-flow]] — primary source for TTS pipeline
- [[infrastructure]] — Docker compose structure, services
- [[vps-setup]] — production deployment details
- [[frontend]] — frontend architecture (lighter coverage in public docs)
- [[stripe-integration]] — billing flow if relevant

## Done When

- `docs/` directory exists with 4+ markdown files
- Each file has at least 2-3 ASCII diagrams
- A non-contributor could understand how the system works from reading them
- Diagrams are accurate against current code (verified post-stabilization)

## Discussion

Initial brainstorm session (2026-02-04): Created sample diagrams for document processing flow covering caching layers, markxiv bypass, website vs document endpoint distinction, and sequence diagram for PDF upload. These serve as style reference for the final docs.
