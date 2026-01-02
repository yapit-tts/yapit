---
status: done
type: research
---

# Task: Work Prioritization & Parallelization Analysis

**Spun off tasks:**
- [[prod-deployment-verification]] - Autonomous deployment testing
- [[model-voice-picker-redesign]] - Voice picker research & design
- [[progress-bar-ux]] - Already existed, ready to go

## Goal

Create a prioritized work list categorized by supervision level, identifying what can be parallelized and what needs user attention.

## Context Gathered

**Active tasks found:**
- `progress-bar-ux.md` - Drag/swipe seeking, hover highlighting
- `private/legal-launch-considerations.md` - GDPR, ToS, launch legal questions

**User's 5am braindump priorities:**
1. Deploy new architecture to prod (testing)
2. Progress bar redesign / mobile layout
3. Credits system - rough draft, errors on login
4. Pricing model brainstorming (credits vs monthly plans)
5. HIGGS vs external API (inworld.ai @ $5/million tokens)
6. Model picker rework - support more Kokoro languages

---

## Prioritized Work List

### Tier 1: High Autonomy (Agent can iterate independently)

These can run with minimal supervision. Agent tests, iterates, reports results.

**1. Production Deployment Testing**
- Deploy current dev to prod
- Verify WS synthesis flow works
- Test document creation end-to-end
- Run basic smoke tests
- **Artifact:** Working prod deployment, test report
- **Supervision:** Just inform when done or blocked

**2. Small Backend/Infra Fixes (Batch)**
- Hetzner backup + restore drill (verify flow works before going live)
- Worker failure/timeout handling (edge case: worker crash → graceful retry?)
- XSS sanitization audit for HTML document display
- **Supervision:** Report findings, ask if any findings need action

**3. Code Quality / Tech Debt Batch**
- Favicon for frontend
- Signup page loading spinners (permanent loading bug)
- Type-check cleanup (if any remaining)
- **Supervision:** None needed

---

### Tier 2: Occasional Feedback (Visual verification)

Frontend work where user reviews occasionally (screenshots, "does this look right?")

**4. Progress Bar UX (Active Task)**
- Drag/swipe seeking
- Hover highlighting (document + progress bar)
- Touch target sizing
- **Supervision:** Visual review at milestones, "try this on mobile"

**5. Model Picker Rework**
- Add all Kokoro languages (French, Chinese, etc. from HuggingFace)
- Better UI for model/voice selection
- Language grouping/filtering
- **Supervision:** UI design decisions, voice naming conventions

**6. Mobile Layout Polish**
- Responsive controls layout
- Touch-friendly interactions
- Full-width progress bar on mobile
- **Supervision:** Mobile screenshots, "does this feel right?"

---

### Tier 3: User Decisions Required

These need your input on direction/strategy. Can't proceed autonomously.

**7. Credits System Fix**
- Current: Errors on login for credits route
- Need to understand current state and decide what credits UI should show
- **Questions:**
  - What should credits page display for now?
  - Just balance? Purchase history? Usage history?
  - Should we hide credits UI entirely until billing is ready?

**8. Pricing Strategy**
From your braindump:
- Credits-only vs monthly plans?
- Monthly may have better retention ("less scary/technical")
- Option: monthly base + credit top-ups
- Consider: inworld.ai API at $5/million tokens vs RunPod HIGGS
- **Decision needed:** Research task or brainstorm session?

**9. HIGGS vs External API**
- inworld.ai: $5/million tokens, managed, potentially faster
- RunPod HIGGS: Self-hosted, variable cost, we control quality
- **Trade-offs to analyze:**
  - Cost per character at our expected usage
  - Latency (cold start issues with RunPod?)
  - Quality comparison
  - Dependency on external service vs self-hosted
- **Suggestion:** Could do a research task comparing costs/quality

**10. Legal Launch Considerations (Active Task)**
- GDPR, ToS, Privacy Policy
- Document storage privacy
- **Status:** Questions captured, needs research or lawyer consult

---

### Tier 4: Deferred / Lower Priority

Not urgent until public launch or more users.

- Rate limiting (#47)
- Admin panel
- Cache eviction tuning
- Cross-device position sync
- ArXiv URL first-class support
- Full document audio download
- Math-to-Speech
- Vim keybindings
- Code syntax highlighting

---

## Parallelization Recommendations

**Ideal parallel work streams:**

1. **Stream A: Prod deployment** (fully autonomous)
   - Deploy, test, report back

2. **Stream B: Progress bar UX** (occasional visual check)
   - Implement drag/swipe, send screenshots

3. **Stream C: Model picker** (needs some design input upfront, then autonomous)
   - After initial direction: implement, send screenshots

**What to NOT parallelize with heavy cognitive load:**
- Credits system decisions (needs your focused attention)
- Pricing strategy (same)
- Legal considerations (same)

---

## Suggested Next Steps

**If you want autonomous work running:**
1. Green-light prod deployment task
2. Green-light progress bar (already has design in task file)
3. Quick model picker direction chat (5 min), then autonomous

**If you want to clear blockers:**
1. Credits system: decide if we hide it, fix errors, or redesign
2. Pricing: brainstorm session or defer?

**Quick wins while thinking:**
- Favicon
- Signup spinner fix
- XSS audit (peace of mind)

---

## Work Log

### 2025-12-29 - Initial Prioritization

**Context gathered:**
- Read architecture.md (massive todo list at bottom)
- Read active tasks: progress-bar-ux.md, legal-launch-considerations.md
- User's 5am braindump captured priorities

**Key insights:**
- Architecture doc has evolved into a catch-all todo list (~50+ items)
- Mix of: quick fixes, research tasks, strategic decisions, nice-to-haves
- User wants to parallelize without constant supervision
- Some items (credits, pricing) need focused discussion before work

**Categorization approach:**
- Tier 1: Agent can complete, just report results
- Tier 2: Visual feedback occasionally (frontend)
- Tier 3: User decision gates progress
- Tier 4: Defer until launch pressure

**Files read:**
- agent/knowledge/architecture.md - main source of todos
- agent/tasks/progress-bar-ux.md - active frontend task
- agent/tasks/private/legal-launch-considerations.md - active research task
