
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

**Before debugging any VPS or production issues**, read these docs first:
- `agent/knowledge/private/dokploy-operations.md` - API auth, Traefik recovery, nginx DNS caching gotcha, env injection
- `agent/tasks/hetzner-deployment.md` - deployment architecture, Stack Auth setup, migration workflow

Common gotchas documented there will save significant debugging time (e.g., nginx caches container IPs after redeploy → 502 errors even though containers are healthy).

## Database Migrations

**CRITICAL: Shared database with Stack Auth.** Yapit and Stack Auth share the same postgres database.
- **Stack Auth tables use PascalCase** (e.g., `Project`, `ProjectUser`, `Team`) — NOT `stack_` prefix
- **Yapit tables use snake_case** (e.g., `ttsmodel`, `usersubscription`, `document`)
- **NEVER drop all tables blindly** — filter by naming convention or use explicit table lists
- Stack Auth also creates enum types and `_prisma_migrations` table

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
- **Table drops require manual migration** — `env.py` filters to only include tables in current models (to avoid touching Stack Auth). When you delete a model, the table is no longer in `MANAGED_TABLES`, so alembic ignores it. Write the `op.drop_table()` manually.
- Data migrations must be added manually (e.g., populating new NOT NULL columns)
- Operation ordering may need adjustment
- Enum changes often need manual tweaks

**After generating:** Run `make dev-cpu` to restart and apply migration + seed data.

### Deploying to Prod

**No special action.** Gateway runs `alembic upgrade head` on startup. Just `scripts/deploy.sh`.

Never run any destructive commands without getting explicit user approval for the exact command you're about to run.

## Dependency Update Checklists

When updating pinned dependencies, check these version-specific integrations:

### Stack Auth (`docker/Dockerfile.stackauth`)

- [ ] Profile image section still hidden in AccountSettings — we use CSS selector `div.flex.flex-col.sm\:flex-row.gap-2:has(span.rounded-full)` to hide it (no S3 configured).

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
Don't commit them with code changes - we'll batch add them later.

**Wikilinks**: Use `[[task-name]]` (not `task-name.md`) when referencing other task/knowledge files. Enables backlink discovery in memex.

**Master doc:**
- `agent/knowledge/architecture.md` - Architecture, decisions, implementation details, known issues/tech debt

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

### Legacy Plans

Old plan files live in `~/.claude/plans/` (searchable via memex). New work uses `agent/tasks/`.
Put less weight on these. All of them are now marked as "done".

## Key Technical Decisions

- **Structured content format**: JSON (not XML) - native to React frontend, Pydantic backend
- **Markdown parsing**: Backend (Python), not frontend
- **Block highlighting MVP**: Highlight current block only (no character/sentence level)
- **Block splitting priority**: Markdown structure → paragraphs → sentence stoppers → hard cutoff
- **Anonymous sessions**: Yes, generate UUID for free browser TTS, claim account later
- **Design philosophy**: Iterate by doing, don't over-plan upfront
- **Theme**: Light/cozy Ghibli aesthetic (warm cream, green primary)

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

**⚠️ CONTEXT WARNING — Large Snapshots:**
Action tools (click, fill, hover, etc.) automatically return full page snapshots. On complex documents this can be **30k+ tokens per interaction** — enough to consume most remaining context in one call.

**Before any DevTools interaction:**
1. **Create your own small test document** — don't use pre-existing documents in the sidebar, they're often huge (real webpages, long docs). Type a few lines of test content yourself.
2. **Sync task file first if context < 50%** — write current findings and next steps before the snapshot might consume remaining context
3. **Prefer screenshots for visual checks** — `take_screenshot` is much smaller than snapshots

**Exceptions:**
- If debugging a specific bug on a known large document, the large snapshot is unavoidable — just be handoff-ready first.
- For many bugs, screenshots lack precision — DevTools snapshots let you inspect element UIDs, exact positioning, and DOM structure. When you need that accuracy, the snapshot cost is worth it.

**If MCP won't connect:** Ask the user to close Chrome so MCP can launch a fresh instance.

**CSS debugging pattern:** When a style isn't applying, don't keep trying fixes at the same DOM level. Immediately trace upward:
```
element (Xpx) → parent (Ypx) → grandparent (Zpx) → ...
```
Find which ancestor is the constraint, fix there. Flex containers especially: children don't auto-stretch width in flex-row parents without `w-full`.

## Stripe Operations

**⚠️ CRITICAL: Before ANY Stripe API operations (CLI, SDK, MCP, scripts):**

1. **Verify test keys in .env:** Run `grep STRIPE_SECRET_KEY .env | cut -d'=' -f2 | cut -c1-8` — must show `sk_test_`
2. **Verify CLI auth:** Run `stripe config --list` or `stripe whoami` — CLI has its own auth, separate from .env. It may point to a different Stripe account entirely.
3. **If live keys:** Run `make dev-env` to switch .env to test keys
4. **Inform user and wait for consent:** Tell the user which Stripe operations you're about to perform and confirm they haven't run `make prod-env` themselves

**The SDK (.env) and CLI can be authenticated to different Stripe accounts!** Always verify both before mixing commands.

This prevents accidentally creating/modifying/deleting resources in production Stripe.

### Stripe MCP

Stripe MCP provides direct API access and documentation search. Uses OAuth.

**Currently authenticated:** Yapit Sandbox. Re-authenticate (`/mcp`) if switching to fresh sandbox or prod account.

**When to use:**
- Quick lookups: "list subscriptions for customer X", "what products exist"
- Searching Stripe docs without leaving terminal
- Ad-hoc operations during debugging

**When NOT to use:**
- IaC setup — use `scripts/stripe_setup.py` (has idempotent upserts, validation)
- Anything you'd want reproducible — script it instead

**Available tools:** `list_customers`, `list_subscriptions`, `list_products`, `list_prices`, `list_invoices`, `search_stripe_documentation`, `get_stripe_account_info`, and more. See [[stripe-integration]] for full list.

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- **No architectural discussions in code comments** - those belong in the architecture doc
- **No useless comments**: Don't add inline comments that restate what code does, don't add untested metrics/claims, don't add "LLM-style" explanatory comments. Comments should only explain non-obvious "why" - if you feel a comment is needed, the code probably needs refactoring instead.
- **Backwards compatibility is NEVER an issue** - This is a rapidly evolving codebase. Don't preserve old approaches alongside new ones. Replace, don't accumulate. If old code needs updating to match new patterns, update it. If old endpoints/configs are superseded, delete them.
- **Critical logic requires edge case analysis first** — For billing, security, data integrity, and other high-stakes code: list edge cases before implementing. Write out "what if user does X then Y" scenarios. The implementation is usually straightforward once scenarios are clear; the bugs come from not thinking through all paths.
- **Stripe Managed Payments has undocumented limitations** — `managed_payments_preview=v1` doesn't support subscription schedules. Test API assumptions before implementing features that depend on them.
- Never use git add -u or git add . — we work with many parallel agents in the same repo.

