
## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.
- Free tier: Browser-side TTS via Kokoro.js (zero server cost)
- Paid tier: Server-side models via RunPod

**GitHub**: https://github.com/yapit-tts/yapit
**Project board**: https://github.com/orgs/yapit-tts/projects/2

Note: We don't work heavily with GitHub issues (solo dev + claude for now -- the local plans workflow is more efficient for us), but the project board is useful for occasionally closing/updating existing / old issues, as needed.

## Build & Test

- Tests, builds, deploys via Makefile
- Test workflow: `.github/workflows/`
- No default values in Settings class - only defaults in `.env*` files
- `make test-local` for basic tests, `make test` for full suite (needs API keys)
- `make dev-cpu` to start backend (or `make dev-mac` on macOS)

## Agent Work Process

### Session Start (MANDATORY)

1. **Check git state**: `git status`, `git branch`, `git log --oneline -5`
2. **ALWAYS read `yapit-architecture.md`** - Critical context, current state, decisions
3. **Read relevant task plans** from index below for additional context

### During Work

- **Create/continue task-specific plan files** for your work
- Commit code frequently - don't accumulate large uncommitted changes

### Plan File Structure

Keep plans **lightweight** - detailed upfront plans become stale fast. Focus on goal and constraints, not detailed how-to steps.

```
Goal: What success looks like (1-2 sentences)
  - Can include: "user tests X in UI and confirms it works"
  - Can include: "ask user about Y decision"

Constraints/Decisions: Key choices that shape the work

Scope: ~5-7 bullets of what's included (not detailed task list)

Open Questions: Things to clarify with user before implementation
  - Don't guess intent - ask if unclear
  - Can be 10 detailed questions if needed, but don't ask for sake of asking

Notes: Findings, discussions, decisions as work progresses
```

**Workflow for unclear requirements:**
1. Create plan with goal + scope + open questions
2. Get user answers
3. Update plan with answers and refined implementation approach
4. Then execute

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

## Plan Files

Plans live in `~/.claude/plans/`.

**Note**: Plan file read/write may require entering plan mode first in some sessions. If you can't access plan files, try entering then exiting plan mode.

**Master doc (ALWAYS read this):**
- `yapit-architecture.md` - Architecture, decisions, implementation details, known issues/tech debt

**Task-specific plans:**

| File | Purpose | PR | Status |
|------|---------|-----|--------|
| `yapit-browser-processor-review.md` | ClientProcessor backend for browser TTS | #48 | Active |
| `yapit-project-review.md` | GitHub project data review, roadmap update | - | Done |
| `virtual-spinning-hammock.md` | Project overview & handover document | - | Reference |
| `ux-ui-strategy-session.md` | MVP feature planning & UX/UI strategy | - | Pending |

Task plans get descriptive names. Keep entries after completion for history.

## Key Technical Decisions

- **Structured content format**: JSON (not XML) - native to React frontend, Pydantic backend
- **Markdown parsing**: Backend (Python), not frontend
- **Block highlighting MVP**: Highlight current block only (no character/sentence level)
- **Block splitting priority**: Markdown structure → paragraphs → sentence stoppers → hard cutoff

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- **No architectural discussions in code comments** - those belong in the architecture doc
- See `~/.claude/CLAUDE.md` for general coding guidelines
