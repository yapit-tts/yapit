
## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.

**GitHub**: https://github.com/yapit-tts/yapit
**Project board**: https://github.com/orgs/yapit-tts/projects/2

Note: We don't work heavily with GitHub issues (solo dev + claude for now -- the local plans workflow is more efficient for us), but the project board is useful for occasionally closing/updating existing / old issues, as needed.

## Development

- **ALWAYS ask user before stopping/restarting Docker services** — they may be actively testing
- **Backend changes require restart** — If you modify backend Python code, tell user: "Backend code changed - please restart with `make dev-cpu`"

## VPS SSH Permissions

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

### What Good Exploration Looks Like

**Example: "Fix a bug where audio doesn't play for some documents"**

1. **Read overview** → see Core section links to [[tts-flow]] and [[document-processing]]
2. **Read both** — the bug could be in either pipeline. Note:
   - tts-flow has "Voice change race condition" gotcha — could this be it?
   - document-processing explains block splitting — maybe blocks aren't getting `audio_block_idx`?
3. **Follow cross-references** — tts-flow links to [[document-processing]] for "how documents become blocks", document-processing links back to [[tts-flow]] for "variant caching"
4. **Read the Key Files tables** — now you know which source files to examine
5. **Check related knowledge** — if it's a WebSocket issue, [[frontend]] might have relevant info

This takes ~30 seconds. Without it, you'd grep around, miss the gotcha, and waste time rediscovering the race condition.

**This applies to brainstorming and discussion too** — not just implementation. Context gathering (knowledge + code + docs/web links where indicated) is required before meaningful discussion.

**Bad exploration:** Read overview, skim one file, skip cross-references and gotchas. Miss critical context.

The knowledge base is a graph, not a tree. Files are flat but connected via `[[wikilinks]]`. You don't load everything — you navigate to what you need with increasing detail.

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

**tre tips:** Always use `-L 10` for full depth. For less output, scope to a specific directory instead of reducing depth (which hides files):
- Full repo: `tre -L 10` (discouraged for this repo; use ls -la for the root, then *full* tre on first-level subdirs)
- Frontend only: `tre frontend -L 10`
- Backend only: `tre yapit -L 10`

`tre` respects `.gitignore` by default. Use `-e`/`--exclude` to additionally exclude:
- Code only (no task files): `tre -e agent -L 10`
- Wildcards work: `tre -e "*.log" -e test_*`

Conversely, `tre agent -L 10` shows all task files including `private/` and `knowledge/` subdirs — useful when specifically looking for task/knowledge files.

## Memex

Semantic search is disabled. Wikilinks provide the necessary structure for this project.

## Coding Conventions

- No default values in Settings class - all configs and defaults in `.env*` files only - single source of truth.
- **Naming**: Prefer names that describe what something *is* over internal jargon (e.g., `kokoro_runpod_serverless_endpoint` over `overflow_endpoint_id`).
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

- important: While the project is private, we only have 2k free minutes on gh ci, include "[skip tests]" anywhere (at the end) of your commit message to avoid running tests in ci (takes 5+mins) if you have tested locally and only made minor changes.
