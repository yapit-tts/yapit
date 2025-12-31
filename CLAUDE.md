
## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.

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
- `make check` for type checking (backend: ty, frontend: tsc + eslint)
- `make dev-cpu` to start backend (or `make dev-mac` on macOS)
  - If no dev user exists after startup (login fails), run `make dev-user` - there's a race condition where stack-auth health check sometimes fails before user creation runs
- **CI timing**: Integration tests take 4-5 minutes (Docker build). Wait for all checks before merging PRs.

## Database Migrations

### Creating a New Migration (Dev)

```bash
make migration-new MSG="description of changes"
```

**Prerequisites:** Models in `domain_models.py` already updated, Python code is valid (imports work).

**What it does:**
1. Starts postgres if needed
2. Drops DB, runs existing migrations to recreate "pre-change" state
3. Generates migration from model diff
4. Auto-fixes SQLModel quirks (`sqlmodel.sql.sqltypes.AutoString()` → `sa.String()`)
5. Tests migration on fresh DB — if this fails, fix before committing

**Always review the generated migration:**
- Autogenerate can't detect renames (sees drop + create)
- Data migrations must be added manually (e.g., populating new NOT NULL columns)
- Operation ordering may need adjustment
- Enum changes often need manual tweaks

**After generating:** Run `make dev-cpu` to restart and apply migration + seed data.

### Deploying to Prod

**No special action.** Gateway runs `alembic upgrade head` on startup. Just `scripts/deploy.sh`.

## Secrets Management

**`.env.sops`** — encrypted secrets (age/sops). Contains both test and live values:
- `STRIPE_SECRET_KEY_TEST`, `STRIPE_SECRET_KEY_LIVE`
- `STRIPE_WEBHOOK_SECRET_TEST`, `STRIPE_WEBHOOK_SECRET_LIVE`
- API keys (RUNPOD, MISTRAL, INWORLD, etc.)

**For dev:** Run `make dev-env` — decrypts sops, transforms `*_TEST` → main var names, removes `*_LIVE` and `STACK_*`. Creates ready-to-use `.env`.

**For prod:** Deploy script uses `*_LIVE` values.

**`.env.dev`** — public (in git), non-secret dev config (ports, Stack Auth dev project, etc.)

## Agent Work Structure

Task files live in `agent/tasks/`, persistent knowledge in `agent/knowledge/`.
Queryable via grep "^status: active" agent/tasks/*.md

**Wikilinks**: Use `[[task-name]]` (not `task-name.md`) when referencing other task/knowledge files. Enables backlink discovery in memex.

**Master doc:**
- `agent/knowledge/architecture.md` - Architecture, decisions, implementation details, known issues/tech debt

### Branch Strategy

- `main` - stable, production-ready
- `dev` - integration branch
- Feature branches merge to `dev` via PR, then deleted

**Merge vs Rebase**: We use merge commits (not rebase) for PRs. Merges preserve commit history which is valuable for `git bisect` when tracking down regressions.

**Releases**: No tags or releases until actual deployment. Version numbers in docs (v0, v1, etc.) are informal priority indicators.

### Legacy Plans

Old plan files live in `~/.claude/plans/` (searchable via memex). New work uses `agent/tasks/`.
Put less weight on these.

| File | Purpose | Status | Read When |
|------|---------|--------|-----------|
| `block-click-investigation.md` | Block click not working on some documents - investigated race condition and handler structure | Investigated | Block click issues, wrapper div onclick, documentBlocks race condition |
| `playback-flicker-and-whitespace.md` | Fix playback flicker, block highlighting, list rendering, whitespace between spans | Done | Playback flicker, DOM-based highlighting, list CSS, paragraph group spacing |
| `xml-support-and-biorxiv-403.md` | XML support evaluation, bioRxiv 403 investigation | Done | XML formats, JATS, bioRxiv access, User-Agent issues |
| `ui-qol-improvements.md` | 404 page, MediaSession sync, hide new doc button on homepage | Done | 404 handling, hardware media keys, sidebar UX |
| `document-qol-features.md` | Source URL clickable title + markdown export buttons | Done | Document export, source URL, copy/download markdown |
| `visual-group-rendering.md` | Render split paragraphs as single `<p>` with `<span>`s to preserve original appearance | Done | Split paragraphs, visual_group_id, paragraph rendering |
| `monitoring-observability-logging.md` | Structured logging with loguru: request tracing, synthesis timing, JSON output for Claude analysis | Ready to Implement | Logging, observability, performance debugging, loguru |
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
| `frontend-structured-document-rendering.md` | Block rendering, click-to-jump | Done | StructuredDocument component, block highlighting |
| `markdown-parser-document-format.md` | Markdown parsing, JSON format | Done | StructuredDocument schema, audioBlockIdx, markdown-it-py |
| `sidebar-polish-retrospective.md` | Rename/delete, theme, dropdowns | Done | Radix dropdown patterns, theme colors, controlled state |
| `rustling-crafting-gosling.md` | SoundTouchJS speed control | Done | Sample rate issues (44100 vs 24000), AudioPlayer, pitch-preserving playback |
| `ux-ui-strategy-session.md` | MVP feature planning | Done | Product direction, voice picker UX, anonymous flow decisions |
| `yapit-browser-processor-review.md` | ClientProcessor backend | Done | ClientProcessor flow, job_id coordination, /tts/submit endpoint |
| `yapit-project-review.md` | GitHub issue status review | Done | - |

## Key Technical Decisions

- **Structured content format**: JSON (not XML) - native to React frontend, Pydantic backend
- **Markdown parsing**: Backend (Python), not frontend
- **Block highlighting MVP**: Highlight current block only (no character/sentence level)
- **Block splitting priority**: Markdown structure → paragraphs → sentence stoppers → hard cutoff
- **Anonymous sessions**: Yes, generate UUID for free browser TTS, claim account later
- **Design philosophy**: Iterate by doing, don't over-plan upfront
- **Theme**: Light/cozy Ghibli aesthetic (warm cream, green primary)

## Codebase Structure

Run `tre -L 10` to get a gitignore-respecting tree view. Always use `-L 10` for full depth - if you want less output, scope to a specific directory instead of reducing depth (which hides files):
- Full repo: `tre -L 10`
- Frontend only: `tre frontend -L 10`
- Backend only: `tre yapit -L 10`

Use liberally: at task start for orientation, when looking for where something lives, after creating/moving files.

## Memex MCP

You have access to markdown vaults via memex. Use them to find past work, discover connections, and document knowledge that helps future sessions.

Vaults:
- /home/max/repos/github/MaxWolf-01/claude-global-knowledge — Your global knowledge: cross-project learnings, user preferences, workflow insights
- ./agent — Project-specific: tasks, architecture decisions, conventions, debugging patterns
- ~/.claude/plans — Legacy plan files (see table above)

Search tips:
- Use 1-3 sentence questions, not keywords: "How does the auth flow handle token refresh?" beats "auth token refresh"
- Mention key terms explicitly in your query
- For exact term lookup, use keywords parameter with a focused query
- For precise "find this exact file/string" needs, use grep/rg instead — memex is for exploration

Workflow: Search to find entry points → Explore to follow connections (outlinks, backlinks, similar notes) → Build context before implementation.

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

**If MCP won't connect:** Ask the user to close Chrome so MCP can launch a fresh instance.

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- **No architectural discussions in code comments** - those belong in the architecture doc
- **No useless comments**: Don't add inline comments that restate what code does, don't add untested metrics/claims, don't add "LLM-style" explanatory comments. Comments should only explain non-obvious "why" - if you feel a comment is needed, the code probably needs refactoring instead.
- **Backwards compatibility is NEVER an issue** - This is a rapidly evolving codebase. Don't preserve old approaches alongside new ones. Replace, don't accumulate. If old code needs updating to match new patterns, update it. If old endpoints/configs are superseded, delete them.
