
## Project Overview

Yapit TTS - Open-source text-to-speech platform for reading documents, web pages, and text.
- Free tier: Browser-side TTS via Kokoro.js (zero server cost)
- Paid tier: Server-side models via RunPod

## Build & Test

- Tests, builds, deploys via Makefile
- Test workflow: `.github/workflows/`
- No default values in Settings class - only defaults in `.env*` files
- `make test-local` for basic tests, `make test` for full suite (needs API keys)
- `make dev-cpu` to start backend (or `make dev-mac` on macOS)

## Agent Work Process

### Session Start (MANDATORY)

1. **Check git state**: `git status`, `git branch`, `git log --oneline -5`
2. **ALWAYS read `yapit-architecture.md`** - Contains critical context, current state, decisions, known issues

### During Work

- **Create task-specific plan files** for your current work (e.g., `yapit-browser-tts.md`)
- Document in the plan file: what you're doing, which branch, decisions made, progress
- Commit frequently - don't accumulate large uncommitted changes

### Session End (MANDATORY)

**ALWAYS update plan files after completing work:**

1. **Update your task-specific plan file**:
   - Mark completed items as done
   - Note blockers, decisions made, state of work
   - If work is complete, mark plan as DONE

2. **Update `yapit-architecture.md`** when merging to dev:
   - Update "Current State" sections if architecture changed
   - Add new technical decisions
   - Update "Known Issues & Tech Debt" section
   - Update branch info

3. **Update this CLAUDE.md** if plan file index changes

### Branch Strategy

- `main` - stable, production-ready
- `dev` - integration branch
- Feature branches merge to `dev` via PR

## Plan Files

Plans live in `~/.claude/plans/`.

**Note**: Plan file read/write may require entering plan mode first in some sessions. If you can't access plan files, try entering then exiting plan mode.

**Master doc (ALWAYS read this):**
- `yapit-architecture.md` - Architecture, decisions, implementation details, known issues/tech debt

**Task-specific plans (created as needed):**

| File | Purpose | Status |
|------|---------|--------|
| `yapit-browser-processor-review.md` | Review feat/browser-processor branch for merge to dev | Active |

Task plans get descriptive names like `yapit-browser-tts.md`, `yapit-anonymous-sessions.md`, etc.

## Key Technical Decisions

- **Structured content format**: JSON (not XML) - native to React frontend, Pydantic backend
- **Markdown parsing**: Backend (Python), not frontend
- **Block highlighting MVP**: Highlight current block only (no character/sentence level)
- **Block splitting priority**: Markdown structure → paragraphs → sentence stoppers → hard cutoff

## Coding Conventions

- No default values in Settings class - defaults in `.env*` files only
- Follow existing patterns in codebase
- See `~/.claude/CLAUDE.md` for general coding guidelines
