---
status: active
started: 2026-01-10
---

# Task: Agent Workflow Overhaul

Complete redesign of the agent knowledge and task management system. Moving from god documents and god commands to a modular, wiki-linked structure with clear separation of concerns.

## Intent

Create a sustainable workflow where:
- Every agent understands the big picture via CLAUDE.md (not per-command explanations)
- Task files capture intent/purpose/assumptions, not implementation logs
- Knowledge files stay accurate through periodic sweeps (not per-session updates)
- Fresh-context sub-agents handle meta-analysis (no sunk-cost bias)
- Wiki-links create small-world topology for progressive disclosure

The goal is a system that doesn't drift, doesn't require constant maintenance vigilance, and lets agents focus on their specific task while being aware of the broader workflow.

## Why This Matters

**Problems with the old approach:**
- God document (architecture.md) grew stale within days
- God command (/task) tried to explain everything, polluting context
- Continuous task file updates wasted tokens and created noise
- Auto-compaction was lossy and myopic
- No mechanism to keep knowledge in sync with code changes
- Folder hierarchies created "is this frontend or infra?" ambiguity

**What we discovered:**
- Armin Ronacher's handoff/pickup pattern replaces continuous updates
- Fresh-context sub-agents avoid "I just wrote this, it must be fine" bias
- Wiki-links enable small-world structure without folder rigidity
- Periodic sweeps > per-session archiving (more holistic, less tunnel vision)
- Hooks can do lightweight intent verification with Haiku

## The Three-Way Split

### Tasks (`agent/tasks/`)
- **Purpose:** Capture intent, goals, assumptions, mental model evolution
- **Lifetime:** Days to a week
- **Content:**
  - Intent/purpose (what user wants, why)
  - Assumptions (explicit and surfaced)
  - Considered & rejected approaches (with reasoning)
  - Discussion history (clarifications, corrections)
  - Wiki-links to relevant knowledge files
- **When created:** Starting work OR capturing a thought/brainstorm/TODO
- **Staleness:** Expected — these are snapshots in time
- **NOT in task files:** Gotchas (→ knowledge), code snippets, implementation logs

### Handoffs (`agent/handoffs/`)
- **Purpose:** Session continuation summaries
- **Lifetime:** Hours to a day (consumed quickly)
- **Content:**
  - What happened in the session
  - Technical context (files touched, decisions made)
  - What's next (aligned with user-specified purpose)
- **When created:** End of session, only when handing off
- **Naming:** `YYYY-MM-DD-slug.md`

### Knowledge (`agent/knowledge/`)
- **Purpose:** Persistent reference documentation
- **Lifetime:** Permanent (maintained via sweeps)
- **Content:**
  - How things work, patterns, workflows
  - Gotchas discovered across multiple tasks
  - Links to code files (paths, not snippets)
  - Links to external docs
- **When updated:** Periodic sweeps, not per-session
- **Structure:** FLAT files, wiki-links for hierarchy (no subfolders)

## Wiki-Link Philosophy

**Why not folders:**
- Folders force single-parent hierarchy
- "Is this infra or billing?" becomes a problem
- Index.md boilerplate in every folder
- Doesn't permit small-world topology

**Wiki-link structure:**
- `overview.md` → links to all major domains
- `backend.md` → links to modules (tts-flow, document-flow)
- `tts-flow.md` → actual content, maybe links to sub-details
- Files can be reached from multiple paths
- Usually 3-4 layers deep

**Direction:** Task files link TO knowledge (bottom-up). Knowledge only links to tasks when historical reasoning is valuable.

**Small-world principle:** Wiki-links are worthless if you link everything to everything. They're worthless if you only have chains. The value is in the carefully curated graph — enough links for discoverability, not so many that navigation is overwhelming.

## Commands to Create

### /task
**Purpose:** Capture intent for new work or thought
**Behavior:**
- Creates/opens task file in `agent/tasks/`
- Date-prefixed going forward: `YYYY-MM-DD-slug.md`
- Focuses on: intent, assumptions, what to clarify
- Links to relevant knowledge files
- Lean — not the "mother command" anymore

### /handoff [purpose]
**Purpose:** Create session continuation summary
**Behavior:**
- Requires explicit purpose (halts if not provided)
- Creates analysis of session
- Writes to `agent/handoffs/YYYY-MM-DD-slug.md`
- Tells user to use `/pickup slug` to continue

Adapted from Armin's handoff.md with wiki-link awareness.

### /pickup [slug]
**Purpose:** Resume from handoff
**Behavior:**
- Lists available handoffs if no slug provided
- Reads handoff file, continues from there

Adapted from Armin's pickup.md.

### /sweep (or /archive)
**Purpose:** Periodic knowledge update from code/commits
**Behavior:**
- Fresh-context sub-agent (avoids tunnel vision)
- Finds last sweep commit (message starts with `sweep:`)
- Reads all commits since then + current diff
- Updates knowledge files to reflect changes
- Commits with `sweep: <summary>`
- Can optionally include uncommitted changes per user specification

**Why periodic sweep:**
- More holistic than per-session updates
- Catches changes from manual edits, other contributors, non-task sessions
- Batched = averages noise and prevents overcorrections
- Fresh agent = no sunk-cost bias, less context pollution for working agents

### /align
**Purpose:** Verify intent alignment, surface assumptions
**Behavior:**
- User invokes in fresh session with Opus — the command IS the fresh agent
- Reads task file + session transcript
- Evaluates 5 criteria: intent clarity, assumption audit, edge cases, mental model match, scope check
- Reports clarifying questions or confirms alignment

### /explain [scope]
**Purpose:** Explain recent changes with fresh eyes
**Behavior:**
- User invokes in fresh session — the command IS the fresh agent
- Reads git diff (or specified scope in natural language)
- Explains what changed and why
- Flags anything that seems off

## Hooks to Create

### Stop Hook (Intent Verification)
**Purpose:** Lightweight intent alignment check
**Mechanism:**
- Haiku prompt-based hook
- Reads task file (if exists) and recent transcript
- Evaluates: Is agent still aligned with intent? Hidden assumptions?
- If concerns: returns `decision: "block"` with clarifying questions
- Claude forced to address before continuing

**Why Haiku:**
- Cheap, fast
- Good enough for surface-level "is this off track?"
- `/align` command exists for deeper analysis with Opus

**Guard against infinite loops:**
- Input JSON includes `stop_hook_active: true` after a hook already blocked once
- If this flag is true, don't block again — let Claude finish
- Otherwise: hook blocks → Claude continues → hook blocks → infinite loop

### Future: Archive Reminder Hook
**Purpose:** Suggest when to run /sweep
**Deferred:** Implement after /sweep command works well

## CLAUDE.md Rewrite

The new CLAUDE.md should:
- Explain the overall workflow philosophy
- Describe the three-way split and when to use each
- List all commands with one-line descriptions
- Explain wiki-link principles
- Make clear: every agent is aware of the system, knows its role, knows what it doesn't need to handle

**Key point:** Agents don't need /task to explain the workflow. CLAUDE.md provides ambient awareness. Commands are focused tools.

## What We're Moving Away From

- **God documents** — Single massive file that tries to cover everything
- **God commands** — /task as the mother of all context
- **Continuous task updates** — "Update task file now" pattern
- **Code snippets in task/knowledge files** — Link to code, don't duplicate
- **Folder hierarchies** — Use wiki-links instead
- **Per-session archiving** — Periodic sweeps are more holistic
- **Auto-compaction reliance** — Explicit handoffs preserve intent

## Supporting Infrastructure

### extract-session.js
Adapt Armin's script to find and parse session transcript.

**TODO:** Handle parallel Claude sessions (race condition)
- Options: Match by first few messages, require named sessions, check session name in JSONL
- Session name might be passed as argument
- Clarify when implementing

### Memex Configuration
- Disable semantic search for this vault (wikilink-focused)
- Use explore tool heavily for backlink/outlink discovery
- Rename tool for migrating old task files

### Task File Renaming
- Old files lack date prefix
- Use last-modified timestamp as heuristic
- Run after other infrastructure is in place

## TODOs

- [x] Create /task command (lean version)
- [x] Create /handoff command (adapt from Armin)
- [x] Create /pickup command (adapt from Armin)
- [x] Create /sweep command → renamed to /distill
- [x] Create /learnings command (session-based knowledge extraction)
- [x] Create /align command (Opus intent verification)
- [x] Create /explain command (fresh-context change explanation)
- [x] Create Stop hook (Haiku intent verification)
- [x] Rewrite CLAUDE.md for workflow awareness
- [x] Refactor into plugin structure
  - [x] Created agent-workflow/ with proper .claude-plugin/, commands/, hooks/, scripts/
  - [x] Added YAML frontmatter to all commands (description, argument-hint, allowed-tools, model)
  - [x] Refined /task with AskUserQuestion guidance (90% thinking first), USE principle, tracking tasks, subtasks
  - [x] Refined /distill with knowledge file guidance (types, when-to-split, principles)
  - [x] Updated CLAUDE.md to be agent-perspective (user edited heavily)
- [x] Create extract-session.js (handle parallel sessions via --name requirement)
- [x] Incorporate improve-skill pattern → /learnings command
- [x] Move plugin to ~/repos/github/MaxWolf-01/agents/memex-workflow/ with plugin name "mx"
- [x] Test plugin install (marketplace setup done)
- [x] Evaluate Armin's Chrome CDP scripts vs Chrome DevTools MCP — skipped, sticking with MCP (works, more ergonomic; Armin's leaner but more manual, would need Linux fixes)
- [x] tmux skill — skipped, no strong use case currently (main value is debuggers with breakpoints)
- [ ] Rename old task files with date prefix — after other work complete
- [ ] Create knowledge structure over entire project (separate sub-task)
  - [ ] Includes moving non-workflow content from CLAUDE.md to knowledge files


## Subtasks

- [[2026-01-10-knowledge-structure]] (to be created) — Build the wiki-linked knowledge skeleton

## Sources

**MUST READ:**
- Armin's agent-stuff repo: `/home/max/repos/github/mitsuhiko/agent-stuff/`
  - `commands/handoff.md` — Purpose-driven handoff pattern
  - `commands/pickup.md` — Handoff resumption
  - `skills/improve-skill/SKILL.md` — Fresh agent for skill improvement
  - `skills/improve-skill/scripts/extract-session.js` — Session transcript extraction
- Claude Code hooks docs: https://docs.anthropic.com/en/docs/claude-code/hooks

**Reference:**
- Armin's web-browser skill — Leaner CDP approach vs MCP (evaluate later)
- Pi extensions qna.ts/answer.ts — Question extraction pattern (Pi-specific, not directly usable)

## Discussion

**Task file updates (late-session clarification):** Task files SHOULD be updated when understanding changes — clarifications, validated assumptions, decisions made. NOT for implementation progress (that's git). The old "continuous updating" was bad because it was work-diary bookkeeping, not intent capture.

**Commands as fresh agents:** When user invokes /align or /explain, THAT IS the fresh agent. No sub-agent delegation needed. The command is the fresh context.

**Plugin naming (2026-01-11):** Decided on "mx" (memex-inspired). Short prefix for commands (`/mx:task`), meaningful connection to memex which powers the workflow.

**No frontmatter types:** Use descriptive filenames (include "-tracking" in name) rather than `type: tracking` in frontmatter. Same principle as wiki-links over folders — naming conventions over rigid structure.

**USE principle:** Applies to both tasks and knowledge. Don't write Unimportant, Self-explanatory, Easy-to-find content.

**When to split files:** Follows software composition principles — split when topic has isolated link cluster, multiple entry points, clear interface, and reduces parent complexity. The test: "see the section on X" → inline; "see the doc on X" → split.

