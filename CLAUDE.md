
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
- **CI timing**: Integration tests take 4-5 minutes (Docker build). Wait for all checks before merging PRs.

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

**Task-specific plans:** (most recent on top)

| File | Purpose | PR / Commit | Status |
|------|---------|-------------|--------|
| `bugs-and-tech-debt.md` | 401 errors, sidebar refresh, code review & cleanup | 8e61185 | Done |
| `prefetching-optimization.md` | Buffer 3+ blocks ahead to prevent playback stutters | - | Planned |
| `frontend-structured-document-rendering.md` | Frontend rendering of structured document blocks | b251854 | Done |
| `markdown-parser-document-format.md` | Markdown parsing pipeline & JSON document format | #50 | Done |
| `sidebar-polish-retrospective.md` | Document rename/delete, theme polish, mobile dropdown fix | - | Done |
| `rustling-crafting-gosling.md` | Playbar: SoundTouchJS speed control, loading states, UI slider | - | Done |
| `ux-ui-strategy-session.md` | MVP feature planning & UX/UI strategy | - | Done |
| `yapit-browser-processor-review.md` | ClientProcessor backend for browser TTS | #48 | Done |
| `yapit-project-review.md` | GitHub project data review, roadmap update | - | Done |

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

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- **No architectural discussions in code comments** - those belong in the architecture doc
- See `~/.claude/CLAUDE.md` for general coding guidelines
