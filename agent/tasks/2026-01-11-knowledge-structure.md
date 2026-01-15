---
status: done
started: 2026-01-11
completed: 2026-01-12
---

# Task: Knowledge Base Initialization

Build the wiki-linked knowledge skeleton for the yapit project. Part of [[2026-01-10-workflow-overhaul]].

## Intent

Create a knowledge base that:
- Captures the actual state of the codebase (code is truth, not old docs)
- Uses wiki-links for navigation (not folder hierarchies)
- Follows USE principle (no Unimportant, Self-explanatory, Easy-to-find content)
- Is maintainable via periodic `/distill` sweeps
- Enables agents to explore and understand the project efficiently

**The goal is NOT documentation for humans** — it's navigable context for agents. The distinction matters: agents can fetch code, follow links, run commands. They don't need prose explanations of what code does.

## Why This Matters

Current state is problematic:
- ~90 task files marked "active" (no lifecycle management)
- Old knowledge files (`architecture.md`) unmaintained and stale
- CLAUDE.md contains both behavioral guidance AND domain knowledge (mixed concerns)
- Existing task/knowledge files weren't maintained properly — unreliable as sources

## Approach

**Depth-first with adjacent exploration** (not skeleton-first):
1. Pick one domain, explore deeply via code
2. Also read adjacent domains' code (TTS relates to frontend, billing, etc.)
3. Write knowledge for that domain grounded in code
4. Move to adjacent domains, repeat
5. Cross-link as relationships emerge

**Why not skeleton-first:** Skeletons become slop. Deep understanding first, structure emerges from that understanding.

**Source weighting:**
- 90% code (the actual source of truth)
- 5% existing task/knowledge files (be cautious — often stale or inaccurate)
- External docs as needed (link, don't copy)

## Domains Identified (From Code)

Based on reading key files (`domain_models.py`, `ws.py`, `billing.py`, `PlaybackPage.tsx`, etc.):

```
overview.md
├── [[tts-flow]]              — WebSocket protocol, processors, workers, caching
├── [[document-processing]]    — Markdown parsing, OCR, block splitting
├── [[billing]]               — Stripe integration, subscriptions, usage
├── [[frontend]]              — PlaybackPage flow, components, state
├── [[infrastructure]]        — Docker, CI/CD, VPS, migrations
├── [[dev-workflow]]          — Make commands, testing, debugging, metrics
├── [[models-voices]]         — TTSModel configs, voice selection
└── [[auth]]                  — Stack Auth, mail servers, session handling
```

**Notes:**
- `auth` might fold into `infrastructure` if small enough
- `caching` is part of `tts-flow`, not separate
- `usage-quotas` is part of `billing`
- This is a graph, not a tree — cross-links between domains expected

## CLAUDE.md Overhaul

Current CLAUDE.md has mixed concerns. Target state:

**Keep in CLAUDE.md (behavioral guidance):**
- Agent Workflow section (stays)
- Coding Conventions (always relevant)
- Project Overview (essential one-paragraph context)
- Codebase Structure tips (preflight commands, tre usage)

**Move to knowledge files:**
- Build & Test → `[[dev-workflow]]`
- Metrics (SQLite) → `[[metrics]]` or part of `[[dev-workflow]]`
- VPS / Production → `[[vps-ops]]` or `[[infrastructure]]`
- Database Migrations → `[[migrations]]` or `[[infrastructure]]`
- Stripe Operations → merge into `[[billing]]`
- Frontend Development (Chrome MCP) → `[[frontend-dev]]` or `[[frontend]]`

**overview.md content:**
- Project purpose (one paragraph)
- Links to all domains with brief descriptions
- Things every implementing agent should read
- Entry point for exploration

## Existing Files Decisions

**Knowledge files to integrate:**
- `architecture.md` — Replace entirely (god doc, marked for replacement)
- `vps-setup.md` — Fold into `[[infrastructure]]` or keep as linked subtopic
- `secrets-management.md` — Fold into `[[infrastructure]]` or keep separate
- `frontend-css-patterns.md` — Fold into `[[frontend]]`
- `stack-auth-dev-setup.md` — Fold into `[[auth]]` or `[[infrastructure]]`

**Task files (~90):**
- Need triage: delete / archive / extract-to-knowledge
- User intervention required for accuracy judgment
- `stripe-integration.md` is obvious knowledge candidate — move as-is to `[[billing]]`

## Process Notes

**This is multi-session work** (1-3 hours, multiple agents/handoffs).

**Per-domain workflow:**
1. `tre` + read key code files for the domain
2. Read any adjacent domain code that relates
3. Read existing task/knowledge files cautiously
4. Write knowledge file grounded in code
5. Add wiki-links to related files
6. Update overview.md links

**Agents must explore deeply** — 10-20+ files per domain minimum. Conservative exploration will produce shallow knowledge.

## Assumptions

- User will provide guidance on task file triage (what's still accurate/relevant)
- Knowledge files describe "what IS" — if code changes, /distill updates knowledge
- No perfect structure upfront — iterate as understanding deepens

## Progress

**Knowledge files created:**
- [x] `[[overview]]` — Entry point with domain links
- [x] `[[tts-flow]]` — Core synthesis pipeline
- [x] `[[document-processing]]` — Markdown → blocks
- [x] `[[infrastructure]]` — Docker, CI/CD (cleaned up, no duplication)
- [x] `[[migrations]]` — Alembic workflow
- [x] `[[auth]]` — Stack Auth integration (cleaned up, email gotchas extracted)
- [x] `[[frontend]]` — React/playback + Chrome DevTools MCP
- [x] `[[env-config]]` — Secrets/env management (renamed from secrets-management)
- [x] `[[dev-setup]]` — Local development
- [x] `[[vps-setup]]` — Production server (added container IP caching gotcha)
- [x] `[[dependency-updates]]` — Version-specific checklists + license checks
- [x] `[[licensing]]` — AGPL compatibility
- [x] `[[security]]` — Stub
- [x] `[[runpod]]` — GPU workers

**Skipped (anti-pattern):**
- `[[models-voices]]` — Code is self-documenting, no knowledge file needed

**Remaining:**
- [x] `[[stripe-integration]]` — Moved from tasks to knowledge (comprehensive tracking issue)
- [ ] `[[metrics]]` — TBD, will build from debugging sessions
- [ ] `[[logging]]` — TBD

## Done When

- [x] `overview.md` exists with domain links and descriptions
- [x] All domains have knowledge files with content grounded in code (except billing, metrics, logging)
- [x] Cross-links create navigable graph (no orphan files)
- [x] CLAUDE.md is lean (behavioral guidance only)
- [x] Existing knowledge files merged or linked appropriately
- [x] Structure reviewed by user

## Sources

**MUST READ (workflow):**
- [[2026-01-10-workflow-overhaul]] — Parent task with full philosophy
- `/home/max/repos/github/MaxWolf-01/agents/memex-workflow/commands/distill.md` — USE principle, when to split files
- `/home/max/repos/github/MaxWolf-01/agents/memex-workflow/README.md` — Wiki-link structure, three-way split

**Code explored this session:**
- `yapit/gateway/domain_models.py` — All database models
- `yapit/gateway/api/v1/ws.py` — WebSocket TTS endpoint
- `yapit/gateway/api/v1/billing.py` — Stripe integration
- `yapit/gateway/processors/tts/manager.py` — Processor routing
- `yapit/gateway/processors/markdown/transformer.py` — Block splitting
- `yapit/contracts.py` — Gateway-worker protocol
- `frontend/src/hooks/useTTSWebSocket.ts` — Frontend WS client
- `frontend/src/pages/PlaybackPage.tsx` — Main playback orchestration

**Existing knowledge (use cautiously):**
- `agent/knowledge/architecture.md` — To be replaced
- `agent/tasks/stripe-integration.md` — Candidate for knowledge conversion

## Discussion

**Workflow meta-concern (raised by user):** `/task` has detailed context about working with task files. `/pickup` doesn't load that context. Agreed approach: put essentials in CLAUDE.md, accept that `/pickup` is for continuation not restructuring. User can invoke `/task` when needed.

**Auth domain:** User confirmed auth/Stack Auth is its own domain, not just infrastructure config. Includes mail servers, service account patterns.

**Zero slop:** User explicitly rejected skeleton/template approach. Deep understanding first, quality over speed.
