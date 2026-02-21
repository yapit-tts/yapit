
## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.

**GitHub**: https://github.com/yapit-tts/yapit (public)

### Core

- `docs/architecture.md` has mermaid diagrams of the overall architecture and sequence flows.
- [[tts-flow]] — Audio synthesis pipeline: WebSocket protocol, Redis queues, pull-based workers, caching. Read for TTS bugs, latency issues, worker scaling.
- [[inworld-tts]] — Inworld API specifics: voices, models, gotchas, cache warming/pinning. Read for Inworld voice issues, warming, voice picker.
- [[document-processing]] — How content becomes blocks: input paths (text/URL/file), Gemini extraction, YOLO figure detection, markdown parsing, block splitting. Read for document upload bugs, extraction failures, rendering issues.
- [[frontend]] — React architecture, component hierarchy, chrome devtools MCP workflows. Read for UI work, frontend debugging.
- [[features]] — User-facing capabilities: sharing, JS rendering, etc.

### Operations

- [[migrations]] — Alembic workflow, MANAGED_TABLES filter, seed data. Read before any DB schema changes.
- [[vps-setup]] — Production server config, Traefik, nginx reverse proxy routing, debugging. Read for prod issues or nginx config changes (`frontend/nginx.conf`).
- [[infrastructure]] — Docker compose structure (base/dev/prod layers), CI/CD pipeline, worker services, config change checklist. Read for deployment issues or adding services.
- [[env-config]] — Secrets management, .env files, sops encryption.
- [[dev-setup]] — **READ BEFORE TESTING.** Test commands, fixture gotchas, uv/pyproject structure. Tests WILL fail without proper env setup.
- [[dependency-updates]] — Version-specific gotchas, license checking. Read before updating/adding dependencies.
- [[metrics]] — TimescaleDB pipeline, event types, dashboard, health reports. Read when adding/modifying metrics.
- [[logging]] — Loguru JSON logging configuration.

**Testing:** You can claim "all tests pass" if and only if `make test-local` passes (after `make dev-cpu` if you made backend changes).

### Other domains

- [[auth]] — Stack Auth integration, token handling.
- [[stripe-integration]] — Token-based billing, waterfall consumption, Stripe SDK gotchas, webhook handling. Read for billing bugs, subscription issues.
- [[security]] — SSRF (Smokescreen proxy), auth trust boundaries, anonymous sessions, frontend XSS architecture, infrastructure hardening, billing security. Read for any security-related work.
- [[licensing]] — Dependency license checking.

### Notes for distill agents

- Upon any metrics/logging changes, update the monitoring agent prompt in `scripts/report.sh`.
- In addition to knowledge, make sure `docs/architecture.md`, `README.md`, etc. are up-to-date.

## Development

- **ALWAYS ask user before stopping/restarting Docker services** — they may be actively testing
- **Backend changes require restart** — If you modify backend Python code, tell user: "Backend code changed - please restart with `make dev-cpu`"
- Running integration tests / "validating everything still works" makes no sense if you applied backend changes, without running make dev-cpu to rebuild it first.
- IF you want to check for unit tests, which works without restarting the gateway, use make test-unit
- If you can debug something without ssh access, e.g. by running make sync-logs and inspecting the logs and metrics locally, do that instead, since ssh requires user approval / unnecessary friction.
- NEVER push in the same Bash tool call as git committing. Generally, NEVER push on your own except being explicitly told to push.
- The pre-commit hook runs ruff (lint + format), ty type checks, and frontend build — no need to run these separately right before committing.

## VPS SSH Permissions

**⚠️ CRITICAL: Destructive operations on prod require explicit user confirmation.**

Before running ANY of these on the prod VPS, get a literal "YES" from the user:
- `docker stop/restart/rm/kill`
- `docker exec` (can modify container state)
- Any file writes (`rm`, `mv`, `echo >`, etc.)
- Database modifications (anything other than SELECT)
- Service restarts, config changes

Ask explicitly: "I need to run `[exact command]` on prod. This will [effect]. Type YES to confirm."

Do NOT assume approval from vague statements like "fix it" or "go ahead". Prod is prod.

## Branch Strategy

- `main` - production (deploys on push)
- `dev` - for batching changes before deploy
- Feature branches for larger isolated work

**When to use feature branches:** Multi-commit refactors, breaking changes, anything that shouldn't go to prod incrementally. Squash-merge when done.

**When to commit directly to main:** Small self-contained changes (assets, config, typo fixes, isolated bug fixes) that don't interfere with ongoing branch work.

**Committing to main while on a feature branch:** Use an ephemeral worktree — no stashing, no branch switching, current directory untouched:
```bash
git worktree add ../yapit-main main
cd ../yapit-main && # commit, push
git worktree remove ../yapit-main
```

**If branches diverge** (ff-only fails): Use `git cherry-pick <commit>` to move commits to main. Then sync:
```bash
git checkout dev && git merge main  # brings dev up to date with main
```

## Codebase Orientation

`tre` for code structure, `mx` for knowledge navigation — don't mix them.

- **Code:** `tre -e agent` scoped to relevant dirs (`tre frontend`, `tre yapit`). Full repo is too noisy.
- **Knowledge:** `mx explore <topic> yapit` or `mx search "<question>" -v yapit`. Don't `tre` the agent/ dir (unless you want to read hundreds of filenames).
- **Recent activity:** `git log --oneline -30`

## Memex

Vault: `yapit` (configured for project root). Semantic search + wikilink navigation.

Don't delegate reading knowledge files.

## Coding Conventions

- No default values in Settings class - all configs and defaults in `.env*` files only - single source of truth.
- **Naming**: Prefer names that describe what something *is* over internal jargon (e.g., `kokoro_runpod_serverless_endpoint` over `overflow_endpoint_id`).
- Follow existing patterns in codebase 
- **No architectural discussions in code comments** - these should be resolved and clear long before code is written - and documented (by the distillation agent) AFTER the code is done and tested.
- **No useless comments**: Don't add inline comments that restate what code does, don't add untested metrics/claims, don't add "LLM-style" explanatory comments. Comments should only explain non-obvious "why" - if you feel a comment is needed, the code probably needs refactoring instead.
- **Backwards compatibility is NEVER an issue** - This is a rapidly evolving codebase. Don't preserve old approaches alongside new ones. Replace, don't accumulate. If old code needs updating to match new patterns, update it. If old endpoints/configs are superseded, delete them.
- **Critical logic requires edge case analysis first** — For billing, security, data integrity, and other high-stakes code: list edge cases before implementing. Write out "what if user does X then Y" scenarios. The implementation is usually straightforward once scenarios are clear; the bugs come from not thinking through all paths.
- Test API assumptions before implementing features that depend on them.
- **Before updating dependencies**, read [[dependency-updates]] — there are version constraints and gotchas that will break prod if ignored.
- Never use git add -u or git add . — we work with many parallel agents in the same repo.
- include "[skip tests]" anywhere (at the end) of your commit message to avoid running tests in ci (takes 10mins) if your changes don't interfere with code that's covered by tests. You don't need to add this for doc changes.

## Legacy Workflow Notes

- Task files that do not follow naming conventions or the structure / content guidelines of the new workflow - Some of these still contain useful context or historical reasoning trails, but are not up to date with our current practices. We keep them for reference; those that are valuable will be wikilinked (more often), naturally. The others can be ignored for almost all purposes.

