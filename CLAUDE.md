
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

## Agent Workflow

This project uses a multi-session workflow with task files, handoffs, and a persistent knowledge base.

### Always Explore the Knowledge Base First

**This is non-negotiable.** Before doing any significant work:

0. YOU READ `agent/knowledge/overview` ALWAYS. REGARDLESS OF WHETHER YOU ARE CREATING A TASK, OR PICKING UP A HANDOFF, OR DOING KNOWLEDGE DISTILLATION.
1. From there, branch out to relevant topics
2. Use memex `explore` to follow wikilinks — outlinks show what a note references, backlinks show what references it
3. Navigate progressively: overview → domain topics → specific topics → concrete content
4. **Follow references in knowledge files** — when a knowledge file points to code files, external docs, or says "see X", read those too when relevant to your task

Knowledge files capture decisions and point to sources — they intentionally don't document code or copy external sources. Code is truth. Follow the pointers to understand implementations, including web links.
Re-read external documentation that is linked from knowledge files to ensure you have the full context.

The knowledge base is a graph, not a tree. Files are flat but connected via `[[wikilinks]]`. You don't load everything — you navigate to what you need with increasing detail.

### The Three-Way Split

| Type | Location | Purpose |
|------|----------|---------|
| **Tasks** | `agent/tasks/` | Intent, goals, assumptions, planning |
| **Handoffs** | `agent/handoffs/` | Session continuation state |
| **Knowledge** | `agent/knowledge/` | Persistent reference docs |

**Tasks** = source of truth for user intent. Not implementation logs (that's git), not code snippets (that's code), not gotchas (that's knowledge).

**Handoffs** = session state for another agent to continue. Created via the **handoff skill**. Marked `consumed: true` after pickup.

**Knowledge** = how things work. Updated via `/distill` (periodic, code-grounded) or `/learnings` (session-grounded).

### Skills Available

- **handoff** — create session continuation for another agent
- **pickup** — resume from a handoff (used when `/task` is given a handoff path)
- **implement** — mindset for moving from planning to coding

The `/task` command orchestrates the workflow and indicates when to use each skill.

### Wiki-Links

Use `[[name]]` (not `name.md`) for task/knowledge references.

Link directions:
- Tasks → Knowledge (task references what it needs)
- Handoffs → Tasks (handoff belongs to a task)
- Knowledge ↔ Knowledge (cross-links)
- Knowledge → Tasks (historical reasoning trails, tracking-issue style; rarer)

**Hierarchy from links, not folders.** Use memex `explore` to follow outlinks/backlinks.

### Notes

Do not commit ./agent/* files together with code changes. They  are commited by the distillation agent or the user separately.

## Branch Strategy

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
Semantic search is disabled. Wikilinks provide the necessary structure for this project.

Vaults:
- `./agent` — Project-specific: tasks, knowledge, handoffs

**Workflow:**
1. Start from a known file (task file, or `[[overview]]` for knowledge)
2. Use `explore` to follow wikilinks — outlinks, backlinks, similar notes
3. `rename` for renaming files that already have outlinks or backlinks

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

