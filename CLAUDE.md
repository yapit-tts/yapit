
Currently we're working towards Yapit TTS v1, aka the first deploy (still private).

## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.
- Free tier: Browser-side TTS via Kokoro.js (zero server cost)
- Paid tier: Server-side models via RunPod

**GitHub**: https://github.com/yapit-tts/yapit
**Project board**: https://github.com/orgs/yapit-tts/projects/2

Note: We don't work heavily with GitHub issues (solo dev + claude for now -- the local plans workflow is more efficient for us), but the project board is useful for occasionally closing/updating existing / old issues, as needed.

## Build & Test

- Run tests, builds, deploys ONLY via Makefile commands
    - This is to ensure these commands are documented, version controlled, and consistent
    - Exceptions for one-off scripts, debugging or similar
- **Docker operations**: Use `make` commands (e.g., `make dev-cpu`), NOT raw `docker compose` commands
    - Make commands handle env vars, build steps, and proper orchestration
    - **ALWAYS ask user before stopping/restarting Docker services** - they may be actively testing
- **CRITICAL: Backend changes require restart** - If you modify any backend Python code (gateway, processors, models, etc.), you MUST tell the user to restart the backend. The running Docker container has the old code. Say explicitly: "Backend code changed - please restart with `make dev-cpu`". Don't keep debugging "why isn't it working" if you forgot this step!
- Test workflow: `.github/workflows/`
- No default values in Settings class - only defaults in `.env*` files
- `make test-local` for basic tests, `make test` for full suite (needs API keys)
- `make dev-cpu` to start backend (or `make dev-mac` on macOS)
  - If no dev user exists after startup (login fails), run `make dev-user` - there's a race condition where stack-auth health check sometimes fails before user creation runs
- **CI timing**: Integration tests take 4-5 minutes (Docker build). Wait for all checks before merging PRs.

## Agent Work Process

### Session Start (MANDATORY)

1. **Check git state**: `git status`, `git branch`, `git log --oneline -5`
2. **ALWAYS read `yapit-architecture.md`** - Critical context, current state, decisions
3. **Read relevant task plans** from index below for additional context

### During Work: Plan Files as Handover Documents

Plan files are **devlogs** - the synthesis of thoughts, decisions, and learnings as code evolves. They're core to the workflow, not a chore.

**Two key purposes:**
1. **Handover:** Working memory that survives context exhaustion. Context can run out unexpectedly (debugging, Chrome DevTools dumps, verbose logs). The plan file ensures the next agent can proceed exactly where you left off with full context - all knowledge necessary for the task, all considerations, all user feedback distilled.
2. **Brainstorm capture:** Short-term todo list and idea staging. Some plans are "Research Needed" or just-started brainstorms - concrete capture of ideas before full execution.

**How to use them:**
- **Create early:** Start a plan file when you begin work, not when running low on context
- **Update continuously:** Not documentation to fill at milestones - update as you work, after each decision or discovery
- **Capture working state:** File should always reflect "where am I right now" - current state, next steps, what you just learned
- **Commit logical units** - don't accumulate large uncommitted changes, but commit coherent chunks not random checkpoints

**Why this matters:**
- When auto-compaction happens, everything important is already in the file
- No panic-implementing as context warnings appear - take time to reflect
- User can review handover content and give feedback before compaction
- Next agent reads handover + referenced files and has all knowledge necessary to proceed exactly as you would have

**Where learnings flow:**
- Task-specific context, decisions, dead ends → **plan file** (stays there)
- Code style learnings, conventions discovered → **CLAUDE.md**
- Architecture decisions, patterns, tech debt → **yapit-architecture.md** (also serves as medium-long term todo list)

Code comments are NOT the place for architectural decisions or work context.

### Plan File Structure

Keep plans **lightweight** - focus on goal, constraints, and issues encountered, not detailed how-to steps. Detailed upfront plans become stale fast.

**Starting structure:**
```
Goal: What success looks like (1-2 sentences)
  - Can include: "user tests X in UI and confirms it works"
  - Can include: "ask user about Y decision"

Constraints/Decisions: Key choices that shape the work

Scope: ~5-7 bullets of what's included (not detailed task list)

Open Questions: Things to clarify with user before implementation
  - Don't guess intent - ask if unclear
  - Can be 10 detailed questions if needed, but don't ask for sake of asking
```

**As work progresses, add:**
```
Current State: Where are you right now?
  - What's done, what you just figured out, any blockers

Next Steps: What you'd do next / if you had infinite context

Notes: Findings, discussions, decisions, dead ends
  - Include "this didn't work because..." for failed approaches
```

**Key behaviors:**
- Update "Current State" and "Next Steps" frequently - critical for handover
- Before context-heavy operations (debugging, DevTools, large reads), quick-update the file
- At the end: distill key learnings into Notes - what worked, what didn't, what the next agent needs to know

**Workflow for unclear requirements:**
1. Create plan with goal + scope + open questions
2. Get user answers
3. Update plan with answers and refined approach
4. Execute, updating Current State/Next Steps as you go

Granular task tracking belongs in working todos during implementation, not the plan file.

### Before Creating PR (MANDATORY)

1. **Update your task plan file** with final status, results, testing notes

2. **Update `yapit-architecture.md`** to reflect merged state:
   - Update architecture sections if changed
   - Add new technical decisions
   - Update "Known Issues & Tech Debt"

3. **Update this CLAUDE.md** - add PR number to plan index

4. **Batch doc updates with code** - include in the PR, not after

### After PR Merges

- Mark task plan status as DONE in index below
- Keep entries for history (don't remove)

### Branch Strategy

- `main` - stable, production-ready
- `dev` - integration branch
- Feature branches merge to `dev` via PR, then deleted

**Merge vs Rebase**: We use merge commits (not rebase) for PRs. Merges preserve commit history which is valuable for `git bisect` when tracking down regressions. Rebasing rewrites history and loses the ability to bisect through individual commits that were on the feature branch.

**Releases**: No tags or releases until actual deployment. Version numbers in docs (v0, v1, etc.) are informal priority indicators, not tracked versions.

## Plan Files

Plans live in `~/.claude/plans/`.

**IMPORTANT: Do NOT use EnterPlanMode tool for creating/updating plan files.** The plan mode tool adds friction (permission prompts, can't edit files, generates random names). Instead:
- Create plan files directly using the Write tool
- Edit them using the Edit tool
- Name files descriptively yourself (e.g., `feature-name.md` or `task-description.md`)

**Master doc (ALWAYS read this):**
- `yapit-architecture.md` - Architecture, decisions, implementation details, known issues/tech debt

**Task-specific plans:** (most recent on top)

| File | Purpose | Status | Read When |
|------|---------|--------|-----------|
| `block-click-investigation.md` | Block click not working on some documents - investigated race condition and handler structure | Investigated | Block click issues, wrapper div onclick, documentBlocks race condition |
| `playback-flicker-and-whitespace.md` | Fix playback flicker, block highlighting, list rendering, whitespace between spans | Done | Playback flicker, DOM-based highlighting, list CSS, paragraph group spacing |
| `xml-support-and-biorxiv-403.md` | XML support evaluation, bioRxiv 403 investigation | Done | XML formats, JATS, bioRxiv access, User-Agent issues |
| `ui-qol-improvements.md` | 404 page, MediaSession sync, hide new doc button on homepage | Done | 404 handling, hardware media keys, sidebar UX |
| `document-qol-features.md` | Source URL clickable title + markdown export buttons | Done | Document export, source URL, copy/download markdown |
| `visual-group-rendering.md` | Render split paragraphs as single `<p>` with `<span>`s to preserve original appearance | Done | Split paragraphs, visual_group_id, paragraph rendering |
| `monitoring-observability-logging.md` | Monitoring, metrics, logging, tracing for gateway and workers | Research Needed | Observability, performance monitoring, debugging, Sentry, OpenTelemetry |
| `in-document-anchor-links.md` | Make relative links like `#methods` scroll to headings | Done | Anchor links, in-doc navigation, heading IDs, link styling |
| `playback-ux-improvements.md` | Position persistence fix, KaTeX rendering, auto-scroll, settings UI | Done | Playback UX, position restore, math rendering, scroll tracking |
| `audio-speed-control.md` | Replace SoundTouchJS with browser native preservesPitch | Done | Audio speed control, playback bugs at high speed |
| `kokoro-cpu-parallelism.md` | Docker replicas for kokoro-cpu, load balancing options, max_parallel removed | Done | Kokoro scaling, worker replicas, parallelism |
| `runpod-cli-knowledge.md` | RunPod CLI reference: pod creation, SSH, file transfer, common issues | Reference | RunPod GPU pods, file transfer, SSH issues |
| `reflective-hopping-pancake.md` | HIGGS voice consistency via context accumulation (pass audio tokens between blocks) | Phase 1: Testing | HIGGS voice consistency, audio tokens, context passing, long-form reading |
| `kokoro-cpu-performance-subblocks.md` | Sub-block splitting for faster time-to-first-block, kokoro CPU perf analysis | Done | TTS latency, block splitting, sub-block highlighting, kokoro scaling |
| `billing-pricing-strategy.md` | Stripe Managed Payments, credit pricing, competitor analysis, Austrian business setup | Decided | Billing integration, pricing, Stripe setup |
| `cloud-storage-provider.md` | S3/R2 evaluation for audio cache and document storage | Decision: Not Needed | Cloud storage, caching strategy, infrastructure |
| `runpod-infra-as-code.md` | RunPod IaC: native adapter, model caching, slim Docker, SDK deploy | Done | RunPod deployment, HIGGS worker, GitHub Actions, model caching |
| `model-voice-picker.md` | Model/voice picker in playback controls | Done | VoicePicker component, voice state, localStorage persistence |
| `plan-index-improvement.md` | Meta: improve plan index | Done | - |
| `higgs-audio-investigation.md` | HIGGS model capabilities, voice params, vLLM vs native | Research Complete | HIGGS integration, voice config params, cold start issues |
| `tts-performance-investigation.md` | Browser TTS perf, WASM slowness | In Progress | Slow synthesis, WASM debugging, prefetch timing |
| `kokoro-js-frontend.md` | Browser TTS (Kokoro.js), anonymous auth | Phase 2 Done | useBrowserTTS hook, anonymous flow, browser TTS bugs |
| `bugs-and-tech-debt.md` | Auth race conditions, dead code cleanup | Done | API provider patterns, isAuthReady, dropdown+dialog state |
| `prefetching-optimization.md` | Audio block buffering | Done | Playback stutters, PREFETCH_COUNT tuning |
| `frontend-structured-document-rendering.md` | Block rendering, click-to-jump | Done | StructuredDocument component, block highlighting |
| `markdown-parser-document-format.md` | Markdown parsing, JSON format | Done | StructuredDocument schema, audioBlockIdx, markdown-it-py |
| `sidebar-polish-retrospective.md` | Rename/delete, theme, dropdowns | Done | Radix dropdown patterns, theme colors, controlled state |
| `rustling-crafting-gosling.md` | SoundTouchJS speed control | Done | Sample rate issues (44100 vs 24000), AudioPlayer, pitch-preserving playback |
| `ux-ui-strategy-session.md` | MVP feature planning | Done | Product direction, voice picker UX, anonymous flow decisions |
| `yapit-browser-processor-review.md` | ClientProcessor backend | Done | ClientProcessor flow, job_id coordination, /tts/submit endpoint |
| `yapit-project-review.md` | GitHub issue status review | Done | - |

Task plans get descriptive names. Keep entries after completion for history.

## Key Technical Decisions

- **Structured content format**: JSON (not XML) - native to React frontend, Pydantic backend
- **Markdown parsing**: Backend (Python), not frontend
- **Block highlighting MVP**: Highlight current block only (no character/sentence level)
- **Block splitting priority**: Markdown structure → paragraphs → sentence stoppers → hard cutoff
- **Anonymous sessions**: Yes, generate UUID for free browser TTS, claim account later
- **Design philosophy**: Iterate by doing, don't over-plan upfront
- **Theme**: Light/cozy Ghibli aesthetic (warm cream, green primary)

## Frontend Development (Chrome DevTools MCP)

Use Chrome DevTools MCP to visually verify changes, test user flows, and debug issues.

**Dev account:** `dev@example.com` / `dev-password-123` (from `scripts/create_user.py`)
- MCP browser has separate session - login required on first use
- Login: navigate to localhost:5173 → click Login → fill form → Sign In

**Key commands:**
- `take_screenshot` — see rendered UI
- `take_snapshot` — get DOM tree with element UIDs
- `click`, `fill`, `fill_form` — interact using UIDs from snapshot
- `list_console_messages` — check for JS errors/warnings
- `resize_page` — test responsive (375x812 for mobile, 1280x800 for desktop)

**Use for:**
- Visual verification after UI changes
- Console error checking (React errors, failed requests)
- Mobile/responsive layout testing
- User flow testing (login → input → playback → controls)
- Edge case verification without manual testing

**Context awareness:**
Action tools (click, wait_for, fill, etc.) automatically return a full page snapshot. On complex documents this can be ~10k tokens per interaction. This is fine—just be aware:

- **Screenshots for visual debugging** - when you need to see the actual rendered UI
- **Document size varies** - test documents might be large; if debugging a specific bug on a known large document, that's unavoidable
- **Before a debugging session** - if you're about to do multiple DevTools interactions on a potentially large page, update your plan file first with current goal and next steps. That way if context gets consumed quickly, you don't lose track of what you were doing
- **Consider test documents** - if testing generic UI behavior (not a specific bug), you can create/use a simple test document to keep snapshots small

Don't be paranoid about this—just factor it in when planning longer debugging sessions.

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- **No architectural discussions in code comments** - those belong in the architecture doc
- **No useless comments**: Don't add inline comments that restate what code does, don't add untested metrics/claims, don't add "LLM-style" explanatory comments. Comments should only explain non-obvious "why" - if you feel a comment is needed, the code probably needs refactoring instead.
- **Backwards compatibility is NEVER an issue** - This is a rapidly evolving codebase. Don't preserve old approaches alongside new ones. Replace, don't accumulate. If old code needs updating to match new patterns, update it. If old endpoints/configs are superseded, delete them.
- See `~/.claude/CLAUDE.md` for general coding guidelines
