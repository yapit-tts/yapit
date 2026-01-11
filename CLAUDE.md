
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
- **Running tests manually**: Use `uv run --env-file=.env.dev pytest ...` — NOT `source .venv/bin/activate && pytest`. The Settings class requires env vars from `.env.dev` to be loaded, and `uv run --env-file` handles this. Without it, you get pydantic validation errors for missing required fields.
- **Unit tests** (`tests/yapit/`) use testcontainers — they're independent and don't need the backend running
- **Integration tests** (`tests/integration/`) connect to localhost:8000 — they need `make dev-cpu` running
- `make check` for type checking (backend: ty, frontend: tsc + eslint)
- `make dev-cpu` to start backend (or `make dev-mac` on macOS)
  - If no dev user exists after startup (login fails), run `make dev-user` - there's a race condition where stack-auth health check sometimes fails before user creation runs
- **CI timing**: Full CI (tests + build + deploy) takes ~10 minutes. Tests alone ~5 min, build+deploy ~5 min.
- **Skip tests on deploy**: Add `[skip tests]` anywhere in commit message to skip CI tests and go straight to build+deploy. Use when you're confident in the change and want faster deploys.
- **New Docker images**: After adding a new image to CI, set its ghcr.io package visibility to public (defaults to private).
- Debugging: Use info logs or set log level to debug before restarting the backend.

## Metrics (SQLite)

Gateway logs metrics to `metrics.db` (SQLite). Useful for debugging performance, understanding usage patterns.

**Table:** `metrics_event` — event_type, timestamp, model_slug, voice_slug, text_length, queue_wait_ms, worker_latency_ms, audio_duration_ms, cache_hit, processor_route, queue_depth, user_id, document_id, etc.

**Event types:** `cache_hit`, `synthesis_queued`, `synthesis_started`, `synthesis_complete`, `synthesis_error`, `eviction_triggered`, `eviction_skipped`, `ws_connect`, `ws_disconnect`, `error`, `warning`

See `yapit/gateway/metrics.py` for schema and query examples.

## VPS / Production Debugging

**Prod server:** `root@46.224.195.97`

Common gotchas documented there will save significant debugging time (e.g., nginx caches container IPs after redeploy → 502 errors even though containers are healthy).

### VPS SSH Permissions

Read-only commands are auto-approved: `docker ps`, `docker logs`, `docker inspect`, `docker stats`, `curl localhost:*`, `sqlite3 ... SELECT ...`.

**⚠️ CRITICAL: Destructive operations on prod require explicit user confirmation.**

Before running ANY of these on the prod VPS, get a literal "YES" from the user:
- `docker stop/restart/rm/kill`
- `docker exec` (can modify container state)
- Any file writes (`rm`, `mv`, `echo >`, etc.)
- Database modifications (anything other than SELECT)
- Service restarts, config changes

Ask explicitly: "I need to run `[exact command]` on prod. This will [effect]. Type YES to confirm."

Do NOT assume approval from vague statements like "fix it" or "go ahead". Prod is prod.

## Dependency Update Checklists

When updating pinned dependencies, check these version-specific integrations:

### Stack Auth (`docker/Dockerfile.stackauth`)

- [ ] Profile image section still hidden in AccountSettings — we use CSS selector `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` to hide it (no S3 configured).

## Secrets Management

**`.env.sops`** — encrypted secrets (age/sops). Naming convention:
- `DEV_*` → dev only (prefix stripped by `make dev-env`)
- `PROD_*` → prod only (prefix stripped by `make prod-env` / deploy)
- `_*` → never copied (reference/inactive)
- No prefix → shared (copied to both)

**For dev:** Run `make dev-env` — decrypts sops, applies convention, creates `.env`.

**For prod:** Deploy script applies same convention for prod.

**`.env.dev`** — public (in git), non-secret dev config (ports, Stack Auth dev project, etc.)

## Agent Workflow

You are an agent in a multi-session workflow. Your job is to execute your current task well. The workflow commands (`/task`, `/handoff`, `/pickup`, etc.) are invoked by the user to orchestrate work across sessions.

### Always Explore the Knowledge Base

**This is non-negotiable.** Before doing any significant work:

1. Always start from `agent/knowledge/overview` and branch out to relevant topics
2. Use memex `explore` to follow wikilinks — outlinks show what a note references, backlinks show what references it
3. Navigate progressively: overview → domain topics → specific topics → concrete content
4. Follow links until you reach the knowledge relevant to your task - read the content of every file on your path (memex verbose mode helps)

The knowledge base is organized as a graph, not a tree. Files are flat but connected via `[[wikilinks]]`. Progressive disclosure: you don't load everything, you navigate to what you need with increasing detail.

### The Three-Way Split

| Type | Location | Purpose | 
|------|----------|---------|
| **Tasks** | `agent/tasks/` | Intent, goals, assumptions, brainstorming, planning |
| **Handoffs** | `agent/handoffs/` | Session continuation, implementation details, detailed state |
| **Knowledge** | `agent/knowledge/` | Persistent reference docs |

**Tasks** = source of truth for user intent. Not implementation logs (that's git), not code snippets (that's code), not gotchas (that's knowledge).

**Handoffs** = session state for another agent to continue. Created via `/handoff`, resumed via `/pickup`. Marked `consumed: true` after pickup.

**Knowledge** = how things work. Updated via `/distill` (periodic, code-grounded) or `/learnings` (session-grounded).

### Stop Hook

An alignment check fires periodically. It reads the task file + recent session and checks:
- Intent clarity
- Unvalidated assumptions worth checking
- Whether scope expansion warrants splitting into separate tasks
- Mental model match between agent and user

If concerns: it blocks and injects clarifying questions you must address. This is automatic.

### Asking Questions

Ask questions (for non-trivial decisions, or matters of personal preference).

*Beforehand*:
- **Do 90% of the thinking** — analyze options, evaluate trade-offs, form a recommendation
- **Present full analysis** — show your reasoning, not just options

**Then ask what you genuinely need** — questions should emerge from analysis, not replace it
- Use the AskUserQuestion tool.

### Wiki-Links

Use `[[name]]` (not `name.md`) for task/knowledge references.

*Rough* direction:
- Tasks → Knowledge (task references what it needs)
- Handoffs → Tasks (handoff belongs to a task)
- Knowledge ↔ Knowledge (cross-links for small-world topology)
- Knowledge → Tasks (historical reasoning trails, "tracking-issues" style; rarer for higher level top knowledge files or workflows/skills)

**Hierarchy from links, not folders.** Files are flat but connected via wikilinks. Use memex `explore` to follow outlinks/backlinks.

### Task File Structure

Created by `/task`. Includes:
- Intent (what user wants, their mental model, the why)
- Explicit assumptions
- Sources (knowledge files, results from search)
- Definition of done, if helpful
- Considered & rejected approaches 
- Discussion history (clarifications, approaches explored, decisions, mental model evolution)

Update task file when understanding changes — clarifications, decisions, validated assumptions. Not for implementation progress (that's git).

**NOT in task files:** Implementation logs, code snippets, gotchas, current state/progress.

### Handoff File Structure

Created by `/handoff`. Includes:
- Purpose (user-specified, required)
- Intent & context
- Technical state (files, decisions)
- Gotchas discovered
- Next step (aligned with purpose)
- Sources (task files, knowledge, external docs)

Frontmatter: `consumed: false` → `consumed: true` immediately after pickup.

### Branch Strategy

- `main` - production (deploys on push)
- `dev` - for batching changes before deploy
- Feature branches for larger isolated work

**Rapid iteration / fixes:** Work on main directly.

**Batched work:** Use dev, merge to main when ready.

**If branches diverge** (ff-only fails): Use `git cherry-pick <commit>` to move commits to main. Then sync dev:
```bash
git checkout dev && git merge main  # brings dev up to date with main
```

## Codebase Structure

**FIRST STEP FOR ANY AGENT — Preflight checklist:**

1. `tre -L 10` — gitignore-respecting tree view for orientation
2. `git log --oneline -30` — recent commits to understand current state, spot relevant changes, identify potential bug sources

**When to run preflight:**
- Starting any task (mandatory)
- Debugging general flows or cross-cutting concerns
- Working on anything that touches more than 2-3 files
- Looking for where something lives
- After creating/moving files

**tre tips:** Always use `-L 10` for full depth. If you want less output, scope to a specific directory instead of reducing depth (which hides files):
- Full repo: `tre -L 10`
- Frontend only: `tre frontend -L 10`
- Backend only: `tre yapit -L 10`

`tre` respects `.gitignore` by default. Use `-e`/`--exclude` to additionally exclude:
- Code only (no task files): `tre -e agent -L 10`
- Wildcards work: `tre -e "*.log" -e test_*`

Conversely, `tre agent -L 10` shows all task files including `private/` and `knowledge/` subdirs — useful when specifically looking for task/knowledge files.

## Memex MCP

You have access to markdown vaults via memex. The primary value is **wikilink navigation** — the `explore` tool for following outlinks, backlinks, and discovering connections.

Vaults:
- `./agent` — Project-specific: tasks, knowledge, handoffs

**Workflow:**
1. Start from a known file (task file, or `[[overview]]` for knowledge)
2. Use `explore` to follow wikilinks — outlinks, backlinks, similar notes
3. Build context through navigation, not just search
4. `rename` for renaming files that already have outlinks or backlinks

**Search tips (when needed):**
- Use 1-3 sentence questions, not keywords
- For exact term lookup, use `keywords` parameter
- For "find this exact file/string", use grep instead

**Semantic search is secondary.** The structure comes from intentional wikilinks. If you find what you need through links, that's preferred over search — it means the knowledge structure is working.

## Coding Conventions

- No default values in Settings class - all configs and defaults in `.env*` files only - single source of truth.
- Follow existing patterns in codebase 
- **No architectural discussions in code comments** - these should be resolved and clear long before code is written - and documented (by the distillation agent) AFTER the code is done and tested.
- **No useless comments**: Don't add inline comments that restate what code does, don't add untested metrics/claims, don't add "LLM-style" explanatory comments. Comments should only explain non-obvious "why" - if you feel a comment is needed, the code probably needs refactoring instead.
- **Backwards compatibility is NEVER an issue** - This is a rapidly evolving codebase. Don't preserve old approaches alongside new ones. Replace, don't accumulate. If old code needs updating to match new patterns, update it. If old endpoints/configs are superseded, delete them.
- **Critical logic requires edge case analysis first** — For billing, security, data integrity, and other high-stakes code: list edge cases before implementing. Write out "what if user does X then Y" scenarios. The implementation is usually straightforward once scenarios are clear; the bugs come from not thinking through all paths.
- Test API assumptions before implementing features that depend on them.
- Never use git add -u or git add . — we work with many parallel agents in the same repo.

## Legacy Workflow Notes

You might occasionaly stumble upon referencse to
- `~/.claude/plans/` - Old plan files - the very first iteration of the workflow (all marked done, now obsolete and can be ignored)
- `architecture.md` - An old "god document" for architecture and todos, that has been replaced by our current workflow.
- Task files that do not follow naming conventions or the structure / content guidelines of the new workflow - Some of these still contain useful context or historical reasoning trails, but are not up to date with our current practices. We keep them for reference; those that are valuable will be wikilinked (more often), naturally. The others can be ignored for almost all purposes.

