---
status: done
type: research
---

**Knowledge extracted:** [[architecture]] (TTS Architecture section updated)

# Task: Batch Mode Strategy - Processing, UX, and Pricing

## Goal

Decide on the processing model for Yapit TTS: real-time streaming vs batch processing vs hybrid. This affects:
- Backend architecture (queue system, worker orchestration)
- Frontend UX (progress indicators, playback timing)
- Pricing/tier structure
- Free tier economics

## Context

**Trigger**: Setting up Hetzner deployment for production. Anticipating that real-time synthesis won't work reliably on cheap VPS cores - even on high-end local CPUs the experience is suboptimal with prefetching.

**Current state**:
- Browser TTS (Kokoro.js) works but is slow/unreliable (WebGPU not universal)
- Server Kokoro planned for VPS but untested at scale
- HIGGS on RunPod serverless has ~10-20s cold start (native adapter), ~30s if no warm worker
- No batch processing infrastructure exists yet

**Existing documentation**:
- `architecture.md` has "Free Tier Strategy: Batch Conversion" section (idea captured, not implemented)
- `billing-pricing-strategy.md` has per-audio-second pricing model decided
- `strategic-context.md` says "measure first after Hetzner deployment, then decide"

## Constraints / Design Decisions

(None locked yet - this is a brainstorming session)

## Assumptions

- [UNVERIFIED] A1: Hetzner CX33 (4 vCPU) won't handle real-time Kokoro synthesis reliably for multiple concurrent users
- [VERIFIED] A2: HIGGS cold start is 30-50s, synthesis 20s+ per block — batch processing required
- [UNVERIFIED] A3: Users are willing to wait for quality TTS if they understand the trade-off
- [VERIFIED] A4: Per-audio-second billing maps well to serverless costs (from billing-pricing-strategy.md)
- [VERIFIED] A5: Kokoro and HIGGS have similar CPS (~13-15) — can use shared estimate
- [VERIFIED] A6: HIGGS context passing works with non-adjacent/garbled context (tested in `scripts/test_higgs_context_fixed.py` - even LaTeX and garbled inputs as context preserved voice consistency for subsequent normal text)
- [UNVERIFIED] A7: Current real-time system doesn't work reliably even for Kokoro (the entire premise of this task)

## Current State

**ARCHIVED 2025-12-28.** Design decided, backend implemented, frontend migration pending.

### Design Decisions (locked in)
- No explicit "batch mode" — just improved parallel prefetching
- Model/mode separation: `kokoro`/`higgs` (model) + `browser`/`server` (mode)
- WS for control messages, HTTP for audio fetch
- Redis queue per model + pubsub for worker→gateway notifications
- Overflow routing when queue depth exceeds threshold

### Backend (implemented, needs e2e testing)
- ✅ WS endpoint (`ws.py`) with synthesis flow
- ✅ Audio endpoint (`audio.py`) for GET + POST
- ✅ Model/mode separation in processors and config
- ✅ Integration tests migrated to WS
- ⚠️ Overflow routing not tested with actual RunPod

### Frontend (POC only, needs full implementation)
- POC blocky progress bar exists but needs rework
- POC parallel prefetch logic exists but uses HTTP, not WS
- Nothing is production-ready

### Remaining (separate tasks)
1. Frontend WS migration + new prefetching implementation
2. Parameter tuning (50/30/20 prefetch) after real-world testing
3. E2e testing with RunPod overflow

**Additional clarifications (2025-12-25):**

- **Default voice preset**: Persist per user in localStorage (already exists?). No DB needed.

- **Auto-prefetch toggle**: Option to start prefetching on document creation (default: on). For users who just want to view without synthesis starting immediately.

- **Pause behavior SIMPLIFIED**: With new parallel system (always 20+ blocks ahead), pause does NOT need special "continue fetching" logic:
  - Fetching only triggers when buffer drops below threshold
  - With 50 initial / 30 threshold, user is always 20+ blocks ahead after first batch
  - Pause just stops audio. Resume has buffer.
  - No need for "pause triggers more fetching" - that would feel odd
  - Just don't cancel in-flight requests on pause

- **Power user "prepare everything" NOT needed**: If prefetch works properly (parallel workers, good buffer), there's just startup latency once, then smooth. No need for explicit "prepare all" framing.

- **Export feature details** (when implemented):
  - Voice settings selection in export dialog
  - Recommend or enforce 1x speed export (speedup is just post-processing)
  - MP3 or WAV format options

- **WebGPU case**: Can't spin up parallel workers. Same algorithm but single-threaded. May not achieve real-time. At minimum: don't cancel in-flight requests on pause, so buffer can build.

## Open Questions

**Resolved (see work log for details):**
- ~~Processing modes~~: No explicit batch mode, just improved parallel prefetching
- ~~Large document UX~~: Parallel prefetch handles it; section selection only in export
- ~~Queue prioritization~~: Per-block, premium gets priority, free queue grows unbounded
- ~~Free tier with premium models~~: Sign-up bonus (5-10 min), not monthly recurring
- ~~Partial playback~~: Yes, start playing when first 2-3 blocks ready
- ~~Synthesis trigger~~: Play = play. Prefetch starts on play, or optionally on document creation
- ~~Pause behavior~~: Just stops audio, in-flight requests complete, buffer remains
- ~~Progress visualization~~: Blocky progress bar showing block states
- ~~Chars-per-second benchmarks~~: DONE - 13 CPS for Kokoro, 15.5 for HIGGS

**Still open:**

1. **Blocky progress bar UI**: Exact design, colors, interaction
2. **OCR page selection**: How to let users specify page ranges before OCR?
3. **Edge case: no headings**: What's the fallback for structureless documents?
4. **Voice switching**: Clears blocky bar, re-prefetches from cursor. UI feedback?
5. **Voice picker samples**: Pre-cached audio samples in voice picker (noted, orthogonal)
6. **Block splitting tuning**: 100 vs 150 vs 200 chars, smarter comma splitting
7. **Export feature design**: Section selection, voice settings, speed options (1x recommended)
8. **Parallel prefetch parameters**: 50/30/20 are starting points, need real-world tuning
9. **WebGPU fallback**: Single-threaded, may not achieve real-time, needs graceful handling
10. **Auto-prefetch toggle**: On document creation, default on, toggle for users who want to view first

**Auto-prefetch on document creation (clarified):**
- Toggle setting: start prefetching on document creation (default: on)
- With parallel prefetch, only first batch (50 blocks) is sent initially
- Not the whole document - just enough for smooth startup
- User can toggle off if they want to view document without any synthesis starting
- Large docs: still only first 50 blocks, not dangerous. Rolling refill as needed.

## Notes / Findings

### User's Initial Thoughts

**Why batch mode seems attractive:**
- Simplifies backend (no "ready in time" coordination)
- Easy progress bars (known block count)
- Queue prioritization is natural (re-rank blocks by tier)
- Cleaner economics (known costs before synthesis starts)
- Free tier can use VPS spare cycles without time pressure

**Why real-time is problematic:**
- High-end local CPU already struggles with prefetching
- Cheap Hetzner cores expected to be worse
- Hidden performance issues need logging/debugging to find
- Unreliable UX is worse than slow-but-predictable UX

**HIGGS/premium considerations:**
- Cold start exists regardless (~10-20s native, ~30s if no warm worker)
- Can't afford always-on worker
- Premium model needs hefty credit multiplier
- Free trial: maybe 1-5 min/month at premium rate?

**Large document problem:**
- Books have indexes, references, prefaces user won't read
- Per-audio-second billing means users pay for unwanted content
- Need way to select specific sections/chapters
- "Full document synthesis" is wasteful for many use cases

**Potential free tier model:**
- Small free credit allocation per month (e.g., 5 min audio at 1x multiplier)
- Premium model uses credits at higher multiplier (e.g., 2x)
- Free users use batch queue (VPS spare cycles)
- Paying users get priority queue + instant synthesis option

---

## Work Log

### 2025-12-24 - Brainstorm Session Started

User initiated brainstorming via /task command. Key concerns:
- Real-time synthesis may not work reliably on Hetzner
- Considering batch processing as primary/only mode
- Questions around large document UX, billing fairness, free tier economics

Context gathered:
- Read architecture.md, billing-pricing-strategy.md, strategic-context.md
- Found existing "Batch Conversion" idea in architecture.md
- HIGGS cold start validated at ~10-20s (native adapter)
- Hetzner deployment in progress (CX33 VPS provisioned)

### 2025-12-24 - Discussion Round 2

**My analysis points shared:**
- "Listen while processing" as core UX (not "batch then listen")
- "Synthesize on demand" for large docs
- Per-block queue priority
- Keeping browser TTS as primary free tier
- Cost math for free monthly credits

**User feedback:**
- Agrees: Listen while processing is the way, clearer UX
- Skeptical: Range selection UI feels clunky, all approaches imagined (minimap, vim keys) feel complex
- Likes: Cursor-relative prioritization (click block 100 → prioritize 100+, deprioritize earlier)
- Important: Free tier queue can grow to millions, VPS processes overnight, as long as premium is served
- Cost correction: GPU is ~$0.31/hr not $0.06/hr. 1000 users × 5 min = ~$26/mo + cold starts
- Shift: Monthly free credits problematic for "idle business" goal. Sign-up bonus (5-10 min) + promotional codes better
- Unsure: When synthesis starts — leaning toward "on document create" for simplicity but not decided
- Note: Headings might be universal enough (papers, books have them) for simple chapter selection

**User's stance on "synthesize on demand" UI:**
Torn. Can imagine solutions but all feel clunky. Maybe smart defaults (cursor-forward) are enough? Maybe chapter-level selection if doc has headings? Not resolved.

**Next:** User will test HIGGS latency on actual documents to get real data before deciding more.

### 2025-12-24 - CPS Benchmark Implementation

Created benchmark script to measure chars-per-second for duration estimates.

**Files created:**
- `scripts/tts_speed_benchmark/corpus.py` — 87 test samples across 20 categories
- `scripts/tts_speed_benchmark/benchmark.py` — PEP 723 script, supports `--kokoro` direct and `--runpod-endpoint`

**Benchmark results (Kokoro):**
- af_heart (female): Median 11.1 CPS overall, ~14-15 CPS for prose
- am_fenrir (male): Median 11.0 CPS overall, ~15-16 CPS for prose
- Edge cases (garbled, fragments, extreme punctuation) drag down average significantly
- Realistic content (prose, technical, scientific, dialogue): ~13-14 CPS

**Decision:** Use 13 CPS as default (80% case optimization, not dragged down by synthetic edge cases)

**Code changes:**
- Updated `_estimate_duration_ms()` default from 20 → 13 with benchmark comment
- Considered per-model DB field, reverted — estimates happen at block creation before model selection

**Learnings:**
- Initial approach tried hitting Docker endpoint (port 8000), but that was the gateway not the worker
- Easier to just run Kokoro adapter directly with `--kokoro` flag instead of HTTP

### 2025-12-24 - HIGGS Testing & Prefetching UX Issues

**HIGGS performance findings (via UI testing):**
- 20s+ per block synthesis time
- 30-50s cold start
- NOT viable for real-time playback without expensive always-warm workers
- Would need aggressive parallel prefetching + multiple workers to serve one user smoothly
- Conclusion: batch processing is the way forward for HIGGS

**Prefetching UX issue discovered:**
- Current behavior: when user pauses, prefetching stops
- Expected behavior: pausing should continue loading ahead so playback resumes smoothly
- With proper prefetching settings (more aggressive), this would be fixed
- But fundamentally, real-time prefetching is fragile — batch processing is more robust

**Benchmark script failure (my mistake):**
- Tried to benchmark HIGGS via RunPod endpoint
- Sent malformed requests: just `{"text": ..., "voice": ...}`
- HIGGS requires `ref_audio` + `ref_audio_transcript` in kwargs (loaded from voice prompts)
- All 87 requests failed, wasted ~$0.10 and user's time
- Fixed script to load voice prompt files for HIGGS benchmarking

**HIGGS CPS result (benchmark script):**
- Median: 15.5 CPS, Mean: 15.08, ±20% variance
- Close enough to Kokoro's 13 CPS for shared estimate
- Long prose sample failed: CUDA OOM on 667 chars - concern for longer blocks

**HIGGS quality issues discovered (via UI testing):**
1. **Voice consistency issues** - sometimes completely different voice mid-document
   - Possibly bugs in how we pass audio context tokens?
   - Need to investigate context accumulation code
2. **Garbled output on certain patterns** - e.g., "[5][6]" (citation brackets) causes entire block to be garbled
   - Model instability on certain character sequences
   - Not necessarily a bug, just model limitation

**Idea: Pre-synthesis text filtering**
- Add regex filter to strip problematic patterns before synthesis
- Examples: citation brackets "[1]", "[5][6]", maybe URLs, special chars
- Settings toggle: "Filter problematic patterns" (on by default)
- Implementation: filter in-place before sending text to synthesize from DB block
- Could be model-specific (HIGGS needs more filtering than Kokoro)
- Trade-off: loses some fidelity but prevents garbled output

### 2025-12-24 - Discussion Round 3: Section-Level Selection

**Key insight reached:** Selection granularity should be SECTIONS (headings), not blocks.

Why this works:
- Matches how users think about documents (chapters, sections, not "block 47")
- 99%+ of documents have headings: books (chapters), papers (Abstract/Methods/References), websites (h1/h2)
- Natural for the common "skip references" use case
- Not clunky micro-management

**Ideas explored and status:**

1. **Block-level selection (health bar with queue eviction)**
   - User was excited about the visual (health bar like video game HP)
   - Long-press to select/deselect queued blocks
   - Green blocks = cached, can toggle queued ones
   - DISMISSED: Probably nightmare of bugs, too granular, cool but impractical
   - KEPT IN MIND: Some form of visual progress feedback still needed

2. **VS Code minimap / range selection**
   - DISMISSED: Clunky, optimizing for ~10 credits, not worth the hassle

3. **"Stop synthesis" button**
   - Simple but user skeptical about UX without visual feedback
   - Not fully dismissed but section-level toggle is cleaner

4. **Section-level toggles (CURRENT DIRECTION)**
   - Show document outline after parsing
   - Checkboxes per section, toggle all on/off
   - Cost estimate updates as user toggles
   - Click "Synthesize" to start
   - Questions still open (see below)

**Scope decision: "Not a text transformation tool"**
- We parse and transcribe, we don't edit/transform content
- For complex preprocessing (remove links, describe images, handle edge cases), users use their own LLM
- We can provide a recommended prompt for best results
- Keeps scope manageable, avoids scope creep

**Edge case: Documents without headings (~1%)**
- Don't build complex UI for this
- Fallback: treat as one big section, or page-level for PDFs
- Could recommend LLM preprocessing for structure

**OCR-specific:**
- Can't detect sections before OCR runs (obviously)
- Granularity for OCR = pages only
- "OCR pages 1-45" style input, not section toggles

**Cost estimation:**
- Need to benchmark: characters-per-second-per-model (it's a constant per model at 1x speed)
- Currently some global constant in code, should be per-model in DB
- HIGGS voices vary more (can be styled), estimates less reliable
- Always treat as rough estimate (±30%)
- Show section DURATION (minutes), not cost breakdown
- Users can calculate credits from minutes + model multiplier

**DONE:** Benchmark script written and run (2025-12-24). Results:
- Kokoro: ~13 CPS for realistic content (prose, technical, scientific, dialogue)
- Edge cases (garbled, fragments, random strings) drag down to ~11 CPS median overall
- Male (am_fenrir) and female (af_heart) voices nearly identical
- Updated `_estimate_duration_ms()` default from 20 → 13 CPS
- Script: `scripts/tts_speed_benchmark/benchmark.py`
- Corpus: `scripts/tts_speed_benchmark/corpus.py` (87 samples across 20 categories)
- Per-model DB field considered but reverted — estimates are block-level (before model selection)

**Open UI/UX questions (not resolved):**
- Auto-start synthesis on document create vs explicit "Synthesize" button?
  - Auto-start = smoother UX, but pays for unwanted content
  - Explicit button = friction, but user controls spend
- What happens when user clicks block in un-selected section?
  - Does clicking kick off that section's synthesis?
  - Smart prefetching from click point?
- How to display cached vs queued vs processing state?
- Toggle behavior when something is already cached?
- Need some visual progress indicator (simpler than health bar)

**What's definitely decided:**
- Section-level granularity for selection (not blocks, not pages except OCR)
- Per-audio-second billing model (already decided earlier)
- Listen-while-processing is the UX goal
- Cursor-relative prioritization (click block N → prioritize N forward)

### 2025-12-25 - Session Continued: Architecture Review & Corrections

User reviewed my analysis and provided extensive corrections. Key learnings:

**My misunderstandings (corrected):**

1. **Cache behavior**: I thought this was complex. It's actually simple:
   - Audio cached in SQLite by variant hash (text + model + voice + codec + params)
   - No TTL for audio - cached permanently until eviction (eviction not yet implemented)
   - Cross-device: different cache entry, expected behavior
   - Storage not a concern, it's a compute/latency saver

2. **HIGGS context chain**: I wrongly assumed sequential synthesis was required.
   - VERIFIED: Using blocks 1-5 as context for blocks 90-100 works fine
   - Tests in `scripts/test_higgs_context_fixed.py` prove this
   - Test 3 (non-adjacent context) and Test 5 (context corruption) passed
   - The voice inconsistency issues are NOT from context chain approach
   - Likely causes: async prefetch interference, model instability (temperature?), or specific content patterns

3. **Real-time "working" assumption**: The ENTIRE PREMISE of this task is that real-time doesn't work. I wrongly based recommendations on "keeping current real-time for Kokoro". Even Kokoro has issues with current infrastructure.

4. **Model-specific behavior**: User explicitly rejected this as confusing ("retarded"). Different features per model = bad UX.

**Ideas dismissed:**
- Direction A (model-specific behavior): Too confusing, different features per model is bad
- My "prefetching fragility" point about pausing: In-flight requests complete, buffer remains. Point was weak.
- "Smart hybrid with voice caching" (Direction C): We already do all of this except background presynthesis - that's literally what batch mode is. Not an innovation.

**Architecture clarifications:**

The audio caching flow:
1. `BlockVariant.get_hash()` creates hash from text + model + voice + codec + params
2. `cache.store(variant_hash, audio)` stores audio (no TTL)
3. `cache.store(f"{variant_hash}:tokens", ...)` stores HIGGS context tokens
4. On next request, cache.retrieve_data() returns audio if cached
5. Different voice = different hash = different cache entry

HIGGS context passing (`tts.py` + `higgs_audio_v2_native.py`):
1. Gateway builds context from up to 3 preceding blocks (`CONTEXT_BUFFER_SIZE`)
2. Retrieves tokens via `cache.retrieve_data(f"{variant_hash}:tokens")`
3. Serializes as pickle of (text, numpy_array) tuples
4. Worker deserializes, uses as `audio_ids_concat` tensor input
5. After synthesis, stores new tokens for next block

**New considerations from user:**

1. **Both use cases benefit from batch**: Even the "exploring/jumping around" use case is better with pre-synthesized blocks - instant skip, no latency on any click.

2. **Voice picker sample feature**: Pre-cached sample audio for each voice. Click play in picker, hear the voice on standard sample. Don't need to test on your own content. Noted for implementation.

3. **Voice configurator playground**: For HIGGS, users might want custom voice configs (temperature, ref audio, etc.). Separate feature, orthogonal to batch mode.

4. **The nice flow problem**: Current UX is great: paste link → see content → play. Batch mode adds friction: section selection, voice selection, wait, confirm. How to not break the flow?

5. **Voice switching mid-batch**: If you've synthesized with voice A, switching to voice B means... what?
   - Frontend clears in-memory cache
   - Backend still has voice A audio cached
   - Could re-queue from current position with voice B
   - But all the voice A audio is "wasted" (still cached, just not used)

6. **Pause/halt batch synthesis**: Need ability to stop a running batch job. User might realize "oh shit this is too big" mid-synthesis.

7. **"Always do entire document" option**: vs explicit section selection each time. Preference toggle?

8. **Block splitting tuning**: Currently ~150 chars. Need to evaluate 100 vs 200 and add smarter splitting (prefer comma splits over hard cutoffs) for better audio flow.

9. **Kokoro on RunPod GPU**: Not tested yet for live mode. Might work, but still won't solve all problems.

10. **Document size threshold**: The question isn't real-time vs batch. It's about auto-synthesis behavior. Small docs could auto-synthesize, but that's confusing (unexpected credit consumption). Probably need explicit "start synthesis" action regardless.

**User's core frustration:**
- RunPod isn't as smooth/reliable as expected
- Infrastructure slowness is the root cause
- Maybe real-time just can't work given current constraints
- Need to rethink the entire synthesis flow, not just add batch mode on top

**Still unresolved:**
- How to make batch mode UX not suck (avoid 3-4 click confirmations)
- Where does voice selection happen? In playbar? In a synthesis dialog?
- What's the trigger for batch synthesis? Explicit button vs auto-start with size threshold?
- Section selection UI still needs design
- Cold start is acceptable for batch (users expect to wait) but blocks real-time
- Always-warm workers are for real-time first-audio latency, not batch mode (I mixed this up)

### 2025-12-25 - Breakthrough: Parallel Prefetching + No Explicit Batch Mode

After extensive discussion, landed on a coherent direction that avoids the "batch mode" framing entirely.

**Core insight: The problem is sequential prefetching, not missing batch mode**

Current state: prefetch 2 blocks sequentially. If synthesis takes 20s/block and playback is 10s/block at 1x (worse at 3x), you fall behind → stutters.

Solution: Parallel prefetching of many blocks at once. Multiple workers process in parallel. Initial wait = (cold start + 1 block), not (cold start + N blocks sequentially).

**No explicit "batch mode" in UX**

Rejected framing:
- "Batch mode" sounds technical/broken
- Explicit "Synthesize" button feels like admitting product is limited
- Separate modes (batch vs real-time) are confusing

Accepted framing:
- Play = play. Hit play, audio prepares, starts when ready.
- Blocky progress bar shows buffer state (blocks filling in)
- User sees what's happening, can start anytime once first blocks ready
- No separate "batch" concept exposed to users

**The blocky progress bar**

Instead of continuous progress slider, show discrete block segments:
- Empty/dim = not synthesized
- Partially filled or different shade = in queue / synthesizing
- Full color = cached, ready to play
- Current playing block = highlighted

This sets expectations visually before user even hits play. Empty bar = "not ready yet, will need to prepare." Full bar = "ready, instant playback."

**Parallel prefetching strategy**

On play pressed:
1. Send initial batch of ~50 block requests in parallel
2. Multiple workers spin up, process concurrently
3. Start playing when first 2-3 blocks are ready (don't wait for all 50)
4. Rest of buffer fills in while user is listening

Continuation - rolling batch refill:
- When (cached blocks ahead of cursor) drops below 30, send another batch of 20
- Check after each block finishes playing
- Simple threshold rule, no "smart" gap monitoring

Flow example:
- Play pressed → 50 blocks sent in parallel
- First few blocks ready → playback starts
- After playing ~20 blocks → buffer is 30 ahead → trigger: send 20 more
- Repeat until end of document

**Pause behavior**

Pause = stop audio, CONTINUE prefetching (builds buffer to 30-50 blocks ahead)

This is critical: pause actually helps build buffer. User pauses, buffer grows, user resumes with smooth playback. Makes pause useful rather than just stopping everything.

**Section selection: export feature only**

Section selection stays OUT of main playback flow. It lives in the export-as-MP3 feature:
- User clicks export
- Section picker appears (checkboxes per heading)
- Synthesis runs in background
- User gets MP3 AND everything is cached for in-app playback

This gives power users a way to "prepare everything" without cluttering the main flow.

**Voice switching**

When voice changes:
- Blocky bar clears (new voice = new synthesis needed)
- Start prefetching from current position with new voice
- User waits again (visible and natural consequence)

**Infrastructure implications**

For RunPod:
- Spin up 4-5 workers in parallel for initial batch
- Current queue scaling (10 requests = spin up second worker) may be too conservative
- More aggressive: see 50 requests, spin up multiple workers immediately
- Cost per block goes up (more worker-hours), price credits accordingly

For VPS:
- Multiple Docker replicas of Kokoro worker
- Multiple cores working in parallel
- Same principle: parallel synthesis > sequential

**Billing adjustment needed**

Must price credits assuming parallel worker usage:
- More workers = higher infra cost per block
- Need to factor this into per-second credit cost
- Can't assume single worker processing

**What still needs testing**

1. VPS Kokoro speed in prod (untested)
2. Kokoro on RunPod GPU (is it faster?)
3. Actual numbers for worker scaling vs playback speed

**Tunable parameters (starting points)**

- Initial batch size: 50 blocks
- Refill threshold: 30 blocks ahead
- Refill batch size: 20 blocks
- All to be tuned based on real usage data and logs

**What this solves**

- No stutters (parallel prefetch outpaces playback)
- No explicit "batch mode" (just improved prefetching)
- No forced long wait (start playing when first blocks ready)
- Clear progress visibility (blocky bar)
- Pause builds buffer (useful behavior)
- Section selection stays simple (export only)

**What's still open**

- Exact UI design for blocky progress bar
- Threshold for "large document" warning (if any)
- Worker scaling parameters (50/30/20 are starting points)
- Credit pricing adjustments for parallel workers
- Testing VPS vs RunPod performance

**Next steps** (updated after implementation)

1. Deploy to VPS and test actual Kokoro CPU performance
2. ~~Implement blocky progress bar in frontend~~ ✅ DONE
3. ~~Implement parallel prefetching logic (initial batch + refill)~~ ✅ DONE
4. ~~Adjust pause behavior to continue prefetching~~ ✅ Already works (in-flight requests complete)
5. Test and tune parameters based on real usage
6. Adjust credit pricing for parallel worker cost

### 2025-12-25 - Implementation Session (Fresh Agent)

Picked up task from previous brainstorming session. Implemented the two core features:

**1. Parallel Prefetching (`PlaybackPage.tsx`)**

Constants (defined at top of file):
- `INITIAL_BATCH_SIZE = 50` - blocks to request when play starts
- `REFILL_THRESHOLD = 30` - trigger refill when buffer drops below this
- `REFILL_BATCH_SIZE = 20` - blocks to request on each refill

New refs/state:
- `prefetchedUpToRef` - tracks highest block index we've triggered prefetch for
- `blockStates` - array of 'pending' | 'synthesizing' | 'cached' for each block
- `blockStateVersion` - counter to trigger re-renders when synthesis starts/completes

Key changes:
- On play start or position jump, trigger batch from current position if buffer is low
- `triggerPrefetchBatch()` fires synthesis for multiple blocks in parallel (fire and forget)
- `checkAndRefillBuffer()` checks cached blocks ahead and triggers refill if needed
- Eviction threshold increased from 5 to 20 (keep more with parallel prefetch)

**2. BlockyProgressBar (`soundControl.tsx`)**

Two rendering modes based on block count:
- **Detailed view (≤100 blocks)**: Individual clickable segments per block
- **Simplified view (>100 blocks)**: Percentage-based bar with position marker

Block state colors:
- pending: `bg-muted` (gray)
- synthesizing: `bg-yellow-500/70 animate-pulse`
- cached: `bg-primary/60`
- current block: brighter, highlighted

Features:
- Click any segment to jump to that block
- Tooltip shows block number and state
- Smooth transitions between states

**Files modified:**
- `frontend/src/pages/PlaybackPage.tsx` - parallel prefetch logic, block state tracking
- `frontend/src/components/soundControl.tsx` - BlockyProgressBar component, replaced Slider

**Build verified:** TypeScript compiles, Vite build succeeds.

**Not yet tested in browser.** User needs to run dev server and test.

### 2025-12-26 - Testing & Feedback

**What works:**
- Blocky progress bar renders (at correct zoom levels)
- Click individual blocks to jump - works
- Dark green highlighting for current block
- Yellow pulsing for synthesizing blocks
- Green for cached blocks
- Tooltips showing block state
- Parallel prefetch fires 50 blocks correctly
- Playback starts when first block ready

**UI issues discovered:**

1. **White stripe rendering inconsistent** - Sub-pixel rendering issue. With 893 blocks in ~500px container, each block is <1px wide. Browser can't consistently render 1px borders at that scale. Stripes appear/disappear at different zoom levels.

2. **Missing slider for scrubbing** - User wants ability to drag through document (old slider with snap-to-block), not just click. For very long documents, clicking tiny blocks is impractical.

3. **Very large docs (893 blocks)** - Health bar doesn't scale well. Blocks too small to see/click.

**Functional issues:**

1. **Non-contiguous synthesis** - Workers grab blocks in arbitrary order from queue. Worker A gets block 17, Worker B gets block 86. Result: cached blocks scattered with gaps, not contiguous. This causes stutters when playback reaches a gap.

2. **Auto-pause bug (unconfirmed)** - User reported playback auto-pausing. Might be related to synthesis failures or state bug.

3. **401 errors** - User is doing Stack Auth changes in parallel, likely cause.

**Infrastructure observations:**

- 2 workers + 50 parallel requests = massive queue
- Synthesis times: 40s (first) → 150s (last) due to queuing
- Local 16-core i9 can't handle more workers efficiently
- VPS options:
  - Current: 4 cores = 1 worker
  - Shared 16 cores: €17.50/month
  - Regular shared 16: €40/month
  - Dedicated 16: €100/month
- Beyond 16 cores → RunPod GPU workers needed

**Ideas for improvement:**

1. **Hybrid progress bar** - Blocky bar for visual state + invisible slider overlay for dragging/scrubbing

2. **Smarter queue scheduling** - Instead of fire-and-forget 50 blocks to backend queue, could:
   - Have frontend prioritize by distance from current position
   - Backend queue could reorder based on playback cursor
   - Or: smaller initial batch (10-20) + aggressive refill from cursor position

3. **Contiguous prefetch** - Maybe don't fire blocks 0-49 all at once. Fire smaller batches: 0-10, then 10-20, etc. Workers more likely to complete contiguously.

4. **Worker pool for RunPod** - Configure HIGGS workers to also process Kokoro queue overflow (or vice versa)

**Open questions:**

1. Should blocky bar always show, or switch to simplified view for huge docs?
2. How to make scrubbing work with blocky bar? Overlay invisible slider?
3. What's optimal batch size given N workers? Maybe batch_size = 2*workers?
4. Auto-pause bug - need to reproduce and debug

---

## Architecture Discussion: Proper Queue System (2025-12-26)

### Problem Statement

Current approach (frontend fires 50 requests, backend processes FIFO) has fundamental issues:
1. No prioritization (premium users wait behind free users)
2. No cursor-relative ordering (block 50 might synthesize before block 5)
3. No eviction (if user jumps, old requests still consume worker time)
4. No overflow capacity (can't spin up serverless when queue is long)

### Requirements

**Must have:**
- Cursor-relative synthesis order (blocks near playback position first)
- Eviction of irrelevant requests (user jumped away)
- No duplicate requests (frontend tracks what's already requested)
- Contiguous completion (minimize gaps in cached blocks)

**Should have:**
- Premium user prioritization
- Overflow to serverless workers for credit-based requests
- Cross-user queue fairness

**Nice to have:**
- Real-time queue status visibility
- Estimated wait time

### Architecture Options

**Option A: Backend Priority Queue (Redis/Postgres)**

```
Frontend                    Gateway                     Workers
   |                           |                           |
   |--POST /synthesize-------->|                           |
   |                           |--INSERT into queue------->|
   |                           |  (priority = cursor_dist) |
   |                           |                           |
   |                           |<--POLL highest priority---|
   |                           |                           |
   |<--SSE/WebSocket progress--|                           |
```

Pros:
- Full control over ordering
- Can evict/reprioritize server-side
- Cross-user fairness
- Can trigger serverless overflow

Cons:
- More infrastructure (Redis)
- More complex
- Need real-time updates to frontend (SSE/WebSocket)

**Option B: Frontend-Controlled Pacing**

```
Frontend                    Gateway                     Workers
   |                           |                           |
   |--POST /synthesize (5 blocks)-->|                      |
   |                           |--process sequentially---->|
   |<--responses---------------|                           |
   |                           |                           |
   |--POST /synthesize (next 5)---->|                      |
   ...
```

Pros:
- Simple, no new infrastructure
- Frontend has full control
- Easy eviction (just don't send more)

Cons:
- No cross-user prioritization
- Premium users can't jump queue
- Round-trip latency between batches

**Option C: Hybrid**

Frontend:
- Tracks all requested blocks (avoids duplicates)
- Sends cursor position with each batch
- Smaller batches (10-20 blocks)
- Can "cancel" by not waiting for old requests

Backend:
- Priority queue with cursor-distance ordering
- Accepts "cursor moved" updates to reprioritize
- Premium flag bumps priority
- Overflow trigger for credit-based requests

### Frontend State Machine

```
Block states:
- pending: not requested yet
- queued: request sent, waiting in backend queue
- synthesizing: worker processing
- cached: audio ready
- evicted: was queued but cursor moved away (don't wait for it)
```

**Tracking what's requested:**
```typescript
const requestedBlocksRef = useRef<Set<number>>(new Set());
// Before sending: check if already requested
// On cursor jump: mark far-away requested blocks as "evicted" (stop waiting)
```

### Eviction Logic

When cursor jumps from position A to position B:

1. Calculate "relevant range": [B - buffer_behind, B + prefetch_ahead]
2. For all blocks in `requestedBlocksRef` that are outside relevant range:
   - If not yet synthesized: mark as evicted, don't wait for response
   - If synthesized: keep in cache (already paid for it)
3. Fire new requests for blocks in relevant range that aren't requested yet

**Backend side:**
- Could accept "evict" messages to skip queued items
- Or simpler: backend processes anyway, frontend just ignores late responses

### Batch Size Considerations

With N workers:
- Optimal batch size ≈ N * 2-3 (keeps workers busy without huge queue)
- For 2 workers: batch of 5-10
- For 8 workers: batch of 20-30

**Aggressive refill:**
- When cached_ahead < threshold (e.g., 5 blocks), immediately fire next batch
- Don't wait for entire batch to complete

### Premium Prioritization

Two approaches:

1. **Separate queues**: Premium queue processed first, free queue only when premium empty
2. **Priority scoring**: score = base_priority + cursor_distance_penalty + age_bonus
   - Premium users get higher base_priority

For serverless overflow:
- If premium user's estimated wait > threshold AND request uses credits
- Spin up serverless worker, route their requests there
- Cost covered by credits

### Constraints/Decisions Needed

1. **Do we need real-time queue updates?** (SSE/WebSocket vs polling)
2. **Backend queue storage?** (Redis for speed, Postgres for simplicity)
3. **Eviction: frontend-only or backend-aware?**
4. **Batch size: fixed or adaptive based on worker count?**

### Next Steps

1. Decide on architecture option (A/B/C)
2. Design queue data model
3. Implement backend queue if needed
4. Update frontend to track requested blocks
5. Implement eviction logic
6. Add premium prioritization
7. Add serverless overflow trigger

---

## Refined Design (2025-12-26 continued)

### Decisions Made

1. **Single Redis queue** - No per-worker queues. Redis atomic operations (BLPOP) handle concurrent access. Per-worker queues would be premature optimization.

2. **8 blocks batch size** - Frontend sends 8 blocks ahead, refills when cached < 8. Power of 2, provides buffer for short blocks.

3. **Backend calculates priority** - Frontend only sends cursor position. Backend determines priority. No security risk from malicious priority values.

4. **Simple priority model**:
   - Priority = request timestamp (FIFO within reasonable range)
   - Cursor position tracked per user
   - Eviction: delete queued items > N blocks behind cursor
   - No complex recalculation needed

5. **One queue + RunPod overflow**:
   - All requests go to single Redis queue
   - VPS workers poll continuously
   - When `queue_length / num_vps_workers > threshold`: also route to RunPod
   - RunPod handles its own autoscaling

6. **All server synthesis costs credits** - No free server tier for now. Simplifies priority (no premium vs free). Browser TTS is free tier.

### Worker Idle Time

Concern: delay between worker finishing and grabbing next request.

Reality: With BLPOP polling, this is just network round-trip (~1-10ms). Negligible compared to synthesis time (seconds). Not a real bottleneck.

### Queue Item Lifecycle (Refined)

```
1. Frontend: "synthesize block X, my cursor is at Y" →
2. Gateway: insert into Redis queue {block_id, user_id, cursor_pos, timestamp, status: "queued"} →
3. Worker: BLPOP, grabs highest priority item, updates status: "processing" →
4. Worker: completes, caches audio, updates status: "done" →
5. Gateway: returns audio to frontend (or frontend polls)
```

### Eviction Logic (Refined)

On cursor move (frontend sends new cursor position):
1. Backend receives new cursor position for user
2. Query queue for this user's items where `block_idx < cursor - buffer_behind` OR `block_idx > cursor + buffer_ahead`
3. Delete those items from queue (only if status="queued", not "processing")
4. Frontend doesn't need to know - it just sends cursor updates

### RunPod Overflow Logic

```python
def should_use_runpod():
    queue_length = redis.llen("tts_queue")
    vps_workers = get_active_vps_worker_count()
    threshold = 3  # e.g., 3 items per worker before overflow
    return queue_length / vps_workers > threshold

def enqueue_synthesis(block, user):
    redis.rpush("tts_queue", serialize(block))

    if should_use_runpod():
        # Also send to RunPod (fire and forget, it handles scaling)
        runpod_client.submit(block)
```

### Data Model Sketch

```python
# Redis queue item
{
    "id": "uuid",
    "user_id": "user-123",
    "document_id": "doc-456",
    "block_id": 789,
    "block_idx": 42,  # position in document
    "cursor_pos": 40,  # user's cursor when request made
    "voice": "af_heart",
    "model": "kokoro-cpu",
    "status": "queued",  # queued | processing | done | evicted
    "created_at": 1703612345.123,
    "worker_id": null  # set when processing starts
}
```

### Frontend State (Refined)

```typescript
// Track what's been requested (avoid duplicates)
const requestedBlocksRef = useRef<Map<number, {
    voiceKey: string,
    status: 'queued' | 'processing' | 'cached' | 'evicted',
    requestedAt: number
}>>(new Map());

// On play or cursor move:
// 1. Calculate blocks [cursor, cursor + 8] that need synthesis
// 2. Filter out already-requested blocks (unless voice changed)
// 3. Send batch request with cursor position
// 4. Mark as 'queued' in local map
```

---

## WebSocket Architecture (2025-12-26)

### Decision: WebSocket for Control, HTTP for Audio

**Why WebSocket:**
- Blocky progress bar needs real-time updates (blocks turn yellow/green instantly)
- Eviction notifications (frontend needs to know when backend evicts jobs)
- 50 parallel HTTP connections is wasteful vs 1 persistent WS
- Cursor updates are frequent - lightweight WS message beats HTTP request
- No polling overhead (current: 500 polls/sec at peak with 50 blocks)

**Architecture:**
- WS: All control messages (synthesize, cursor_moved, status updates, eviction)
- HTTP: Audio data fetch (large binary, cacheable)

### Queue Naming

**Corrected**: Single queue per model, infrastructure-agnostic:
- `tts:queue:kokoro` (not `kokoro-cpu` - workers can be CPU or GPU)
- `tts:queue:higgs`

Workers pull from their model's queue regardless of whether they're CPU/GPU/serverless.

### Cursor Position Storage

**Decision: Redis per (user_id, document_id)**
- Key: `cursor:{user_id}:{document_id}` → `{block_idx: 42, updated_at: timestamp}`
- Updated via WS message when cursor moves
- Backend uses for eviction logic
- Stale cursor if frontend crashes = acceptable (no active playback anyway)

### WebSocket Message Protocol

```typescript
// Client → Server
{type: "synthesize", document_id: "uuid", blocks: [1,2,3,4,5,6,7,8], cursor: 0, voice: "af_heart", model: "kokoro"}
{type: "cursor_moved", document_id: "uuid", cursor: 50}

// Server → Client
{type: "status", document_id: "uuid", block_idx: 1, status: "queued"}
{type: "status", document_id: "uuid", block_idx: 1, status: "processing"}
{type: "status", document_id: "uuid", block_idx: 1, status: "cached", audio_url: "/audio/{variant_hash}"}
{type: "evicted", document_id: "uuid", block_indices: [1,2,3,4]}
{type: "error", document_id: "uuid", block_idx: 1, error: "synthesis_failed"}
```

### Worker → Gateway Notification

Current: Workers cache audio, clear inflight lock. Gateway polls cache.

New: Workers publish to Redis pubsub after completion:
```python
# Worker after synthesis completes:
await redis.publish(f"tts:done:{user_id}", json.dumps({
    "document_id": str(document_id),
    "block_idx": block_idx,
    "variant_hash": variant_hash,
    "status": "cached"
}))
```

Gateway subscribes to user's channel, pushes status to their WS connection.

### Connection Manager

```python
# Gateway maintains active connections
connections: dict[str, WebSocket] = {}  # user_id → WebSocket

async def on_connect(user_id: str, ws: WebSocket):
    connections[user_id] = ws
    # Subscribe to Redis pubsub for this user
    await pubsub.subscribe(f"tts:done:{user_id}")

async def on_disconnect(user_id: str):
    del connections[user_id]
    await pubsub.unsubscribe(f"tts:done:{user_id}")

async def push_to_user(user_id: str, message: dict):
    if ws := connections.get(user_id):
        await ws.send_json(message)
```

### Audio Fetch (HTTP)

Audio stays HTTP for:
- Large binary data
- Browser caching (Cache-Control headers)
- Simple GET request

```
GET /audio/{variant_hash}
→ 200 OK, audio/pcm, X-Duration-Ms: 1234
```

Frontend receives `audio_url` in status message, fetches via HTTP.

### Implementation Components

| Component | Location | Lines (est) | Notes |
|-----------|----------|-------------|-------|
| WS endpoint | `gateway/api/v1/ws.py` | 100-150 | FastAPI WebSocket, auth, message routing |
| Connection manager | `gateway/ws_manager.py` | 50-80 | Track connections, pubsub subscription |
| Message schemas | `contracts.py` | 30-50 | Pydantic models for WS messages |
| Worker pubsub | `processors/tts/base.py` | 20-30 | Publish on completion |
| Audio endpoint | `gateway/api/v1/audio.py` | 30-40 | Simple GET for cached audio |
| Frontend WS client | `frontend/src/lib/ws.ts` | 100-150 | Connect, reconnect, message handling |
| Frontend hook | `frontend/src/hooks/useTTSWebSocket.ts` | 80-100 | React integration |
| **Total** | | **~450 lines** | |

### Migration Path

1. **Phase 1**: Add WS endpoint + connection manager (backend)
2. **Phase 2**: Add Redis pubsub to workers
3. **Phase 3**: Add audio fetch endpoint
4. **Phase 4**: Frontend WS client + hook
5. **Phase 5**: Update PlaybackPage to use WS instead of HTTP synthesis
6. **Phase 6**: Remove old HTTP long-polling synthesis endpoint (or keep for fallback)

### Open Questions (Resolved)

- ~~Separate queues per model?~~ → Yes, `tts:queue:{model}`
- ~~Cursor storage?~~ → Redis per (user_id, document_id)
- ~~WebSocket vs polling?~~ → WebSocket for control, HTTP for audio
- ~~Synthesis over WS?~~ → Control messages only, audio via HTTP GET

---

## Code Review for Handoff (2025-12-26)

### Backend Changes Required

**`yapit/contracts.py`** (55 lines)
- `get_queue_name()` at line 18: Currently returns `tts:queue:{model_slug}`. The model_slug includes infra type (e.g., `kokoro-cpu`). Need to extract base model or rename queues.
- `SynthesisJob`: Add `document_id` and `block_idx` fields - needed for pubsub status messages
- Add new WS message schemas (Pydantic models)

**`yapit/gateway/processors/tts/base.py`** (157 lines)
- Line 136: After `redis.delete(TTS_INFLIGHT...)` - add pubsub publish:
  ```python
  await self._redis.publish(f"tts:done:{job.user_id}", json.dumps({
      "document_id": str(job.document_id),
      "block_idx": job.block_idx,
      "variant_hash": job.variant_hash,
      "status": "cached"
  }))
  ```
- Line 149: `brpop` stays for pulling jobs
- Need to track `status: processing` in Redis when job starts (new)

**`yapit/gateway/api/v1/tts.py`** (248 lines)
- Line 202-215: `SynthesisJob` creation - add `document_id` and `block_idx` fields
- Keep endpoint for backwards compatibility / fallback, but new flow uses WS
- Line 215: `redis.lpush(get_queue_name(...))` - keep for now, WS handler will do same

**New files needed:**
- `yapit/gateway/api/v1/ws.py` - WebSocket endpoint
- `yapit/gateway/ws_manager.py` - Connection manager + pubsub listener
- `yapit/gateway/api/v1/audio.py` - Simple GET endpoint for cached audio

### Frontend Changes Required

**`frontend/src/pages/PlaybackPage.tsx`** (~900 lines)
- Lines 397-502: `synthesizeBlock()` - HTTP POST per block → WS message + HTTP audio fetch
- Lines 504-528: `triggerPrefetchBatch()` - becomes single WS "synthesize" message
- Lines 137-138: `blockStates` + `blockStateVersion` - will be driven by WS status messages
- Lines 114-115: `audioBuffersRef` + `synthesizingRef` - keep for audio caching, but status comes from WS

**New files needed:**
- `frontend/src/lib/ttsWebSocket.ts` - WS client with reconnection
- `frontend/src/hooks/useTTSWebSocket.ts` - React hook wrapping WS

**Key refactor:**
Current flow:
```
triggerPrefetchBatch() → for each block → synthesizeBlock() → HTTP POST → poll for response
```
New flow:
```
WS.send({type: "synthesize", blocks: [...]}) → WS receives status updates → on "cached" → HTTP GET audio
```

### Database Changes

**None required** - existing `BlockVariant`, `Block` tables work as-is

### Redis Changes

**New keys:**
- `cursor:{user_id}:{document_id}` → `{block_idx: N, updated_at: timestamp}`
- `tts:status:{variant_hash}` → `queued | processing | cached | evicted` (optional, for status queries)

**New pubsub channels:**
- `tts:done:{user_id}` - worker publishes on completion

**Queue rename (optional):**
- `tts:queue:kokoro-cpu` → `tts:queue:kokoro` (if we want model-only naming)

### Testing Considerations

- WS auth: Use same Stack Auth token as HTTP
- WS reconnection: Frontend must handle disconnects gracefully
- Race condition: Block requested via WS, cached before WS handler sees it → handle gracefully
- Browser TTS: Still works independently (no WS needed for local synthesis)

### Implementation Order Recommendation

1. **Backend first**: WS endpoint + pubsub (can test with simple WS client)
2. **Audio endpoint**: Simple GET, test with curl
3. **Frontend WS client**: Connect, send synthesize, log status messages
4. **Frontend integration**: Replace HTTP synthesis with WS flow
5. **Cleanup**: Remove debug logs, handle edge cases

### Files to NOT Touch

- `yapit/workers/` - Adapters and handlers are fine, no changes needed
- `yapit/gateway/cache.py` - Caching works as-is
- `frontend/src/lib/browserTTS/` - Browser TTS is independent

---

## Architecture Refactor: Model + Mode Separation (2025-12-26)

### Problem with Current Approach

Started implementing `model_family` field to map slugs like `kokoro-cpu` → queue `tts:queue:kokoro`. But this exposed a deeper issue:

**Current state (messy):**
- DB has separate entries: `kokoro-cpu`, `kokoro-client-free`, `higgs-native`
- These are the SAME model, just different deployment targets
- `credits_per_sec` baked into each entry (0 for browser, 1.0 for server)
- tts_processors.json duplicates model identity with infra routing
- Frontend picks `kokoro` vs `kokoro-server` as if they're different models

### Decision: Separate What, Where, How Much

**What** (model identity) - DB:
- One entry per actual model: `kokoro`, `higgs`
- Contains: voices, sample_rate, native_codec, etc.
- `credits_per_sec` = cost when using server-side synthesis

**Where** (synthesis mode) - Request parameter:
- `synthesis_mode: "browser" | "server"`
- Browser = synthesize in user's browser via WASM/WebGPU
- Server = synthesize on backend (VPS worker or RunPod overflow)

**How Much** (billing) - Derived:
- Browser mode = free (no server cost)
- Server mode = charge `model.credits_per_sec`

### New Data Model

```python
# TTSModel (one entry per actual model)
class TTSModel:
    slug: str          # "kokoro", "higgs"
    name: str
    credits_per_sec: Decimal  # charged when mode=server
    # audio format
    sample_rate: int
    channels: int
    sample_width: int
    native_codec: str
    # relationships
    voices: list[Voice]
```

### New API Contract

```python
# Synthesis request
{
    "model": "kokoro",           # model identity
    "voice": "af_heart",
    "synthesis_mode": "browser"  # or "server"
}

# Billing logic
if synthesis_mode == "browser":
    credits_charged = 0
else:
    credits_charged = model.credits_per_sec * duration_seconds
```

### Processor Routing

tts_processors.json becomes infrastructure routing, not model identity:

```json
{
  "kokoro": {
    "browser": "yapit.gateway.processors.tts.client.ClientProcessor",
    "server": {
      "processor": "yapit.gateway.processors.tts.local.LocalProcessor",
      "worker_url": "http://kokoro-cpu:8000"
    }
  },
  "higgs": {
    "server": {
      "processor": "yapit.gateway.processors.tts.runpod.RunpodProcessor",
      "runpod_endpoint_id": "xxx"
    }
  }
}
```

Or simpler: hardcode routing logic, config just has endpoint URLs/IDs.

### Queue Naming

With this refactor, queue name is just `tts:queue:{model}`:
- `tts:queue:kokoro` - all server-side kokoro jobs
- `tts:queue:higgs` - all higgs jobs

Browser mode doesn't use queues (ClientProcessor).

### Migration Steps

1. **DB refactor**: Consolidate to one entry per model, remove `model_family` field
2. **Seed update**: One kokoro, one higgs
3. **API update**: Take model + mode, route to correct processor
4. **Billing update**: Charge based on mode, not model entry
5. **Frontend update**: model + mode selection (can defer, backwards compat possible)
6. **Config refactor**: Restructure tts_processors.json or inline routing

### Backwards Compatibility

During transition, can map old slugs:
- `kokoro-cpu` → model=kokoro, mode=server
- `kokoro-client-free` → model=kokoro, mode=browser
- `higgs-native` → model=higgs, mode=server

### Benefits

- Cleaner mental model: model identity ≠ deployment target
- No duplication between DB and config
- Simpler queue naming
- Billing logic is explicit (mode-based, not model-entry-based)
- Easier to add new deployment targets (e.g., kokoro on RunPod GPU) without new DB entries

---

## Work Log

### 2025-12-26 - Model/Mode Separation Implementation

Implemented the model + mode architecture refactor. Key changes:

**Completed:**
- `domain_models.py`: Removed model_family field (slug IS the model identity now)
- `dev_seed.py`: Consolidated to one entry per model (kokoro, higgs)
- `contracts.py`:
  - `SynthesisParameters.model_slug/voice_slug` → `model/voice`
  - Added `SynthesisMode = Literal["browser", "server"]`
  - Added WS message schemas (`WSSynthesizeRequest`, `WSBlockStatus`, `WSEvicted`)
  - Added `get_pubsub_channel(user_id)` helper
- `tts_processors.dev.json` / `tts_processors.prod.json`: New structure with model/mode/backend/overflow
- `TTSProcessorManager`: Refactored with `SynthesisRoute` dataclass, `get_route(model, mode)` method
- `BaseTTSProcessor`:
  - Takes `model` parameter for queue naming
  - Added pubsub publish after job completion (WSBlockStatus)
- `config.py` / `.env.*`: Added `TTS_OVERFLOW_QUEUE_THRESHOLD` setting
- `deps.py`: Updated `get_client_processor` to use new routing
- `tts.py`: Updated SynthesisJob with document_id, block_idx

**Still TODO:**
- Alembic migration (or reset DB in dev)
- Frontend model/mode selection
- Full WS endpoint implementation
- Testing

**Files modified:**
- `yapit/gateway/domain_models.py`
- `yapit/gateway/dev_seed.py`
- `yapit/contracts.py`
- `yapit/gateway/processors/tts/manager.py`
- `yapit/gateway/processors/tts/base.py`
- `yapit/gateway/config.py`
- `yapit/gateway/deps.py`
- `yapit/gateway/api/v1/tts.py`
- `tts_processors.dev.json`
- `tts_processors.prod.json`
- `.env.dev`
- `.env.prod`

Imports verified working. DB needs reset due to schema change (model_family removed, models renamed).

### 2025-12-26 - WS Endpoint + Audio Endpoint Implementation

Implemented the WebSocket synthesis flow and audio fetch endpoint:

**New files:**
- `yapit/gateway/api/v1/ws.py` - WebSocket endpoint with:
  - `authenticate_ws` for token/anonymous auth via query params
  - `_queue_synthesis_job` with overflow routing logic (checks queue depth vs threshold)
  - `_handle_synthesize` processes batch of blocks, returns immediate status for cached blocks
  - `_pubsub_listener` subscribes to `tts:done:{user_id}` and forwards status updates
  - Cursor tracking placeholder (TODO)
- `yapit/gateway/api/v1/audio.py` - Simple GET `/v1/audio/{variant_hash}` endpoint
- `yapit/gateway/auth.py` - Added `authenticate_ws` function

**Key implementation details:**
- Cache is shared globally by variant_hash (text + model + voice + params)
- Document ownership check is authorization, not cache isolation
- Overflow routing: if `queue_depth > threshold`, routes directly to overflow processor (RunPod)
- WS returns immediate "cached" status for cache hits, "queued" for new jobs
- Pubsub listener runs as background task per WS connection

**Still TODO:**
- Reset dev DB and test end-to-end
- Update existing tests
- Frontend WS client + model/mode UI
- Cursor tracking + eviction logic (placeholder in WS handler)

### 2025-12-26 - Implementation State Analysis (New Session)

Reviewed all uncommitted changes. Current implementation state:

**Backend - COMPLETE:**

| Component | Status | Notes |
|-----------|--------|-------|
| `contracts.py` | ✅ | `SynthesisMode`, WS message schemas, pubsub helper |
| `ws.py` | ✅ | Credit check, BlockVariant DB, context tokens, overflow routing, pubsub listener |
| `audio.py` | ✅ | GET `/v1/audio/{variant_hash}` |
| `base.py` | ✅ | Pubsub publish on completion, credit deduction |
| `manager.py` | ✅ | `SynthesisRoute` dataclass, `get_route(model, mode)` |
| `dev_seed.py` | ✅ | Consolidated to `kokoro` + `higgs` models |
| `auth.py` | ✅ | `authenticate_ws` function |
| `tts_processors.*.json` | ✅ | New structure with model/mode/backend/overflow |

**Tests - MIGRATED TO WS:**

| Test File | Status | Notes |
|-----------|--------|-------|
| `conftest.py` | ✅ | `TTSWebSocketClient` class, `admin_ws_client`/`regular_ws_client` fixtures |
| `test_tts.py` | ✅ | Uses `admin_ws_client.synthesize()` |
| `test_tts_billing.py` | ✅ | All 4 tests migrated to WS |
| `test_client_tts.py` | ❌ | Still uses HTTP `/synthesize` - needs update or removal |

**Frontend - NOT STARTED:**

| Component | Status | Notes |
|-----------|--------|-------|
| `PlaybackPage.tsx` | ❌ | Still uses HTTP long-polling |
| WS client | ❌ | Not implemented (could use existing `useWS.ts` hook) |

**Still TODO:**

1. **Cursor tracking + eviction** - `ws.py` line 332-333 has placeholder:
   ```python
   elif msg_type == "cursor_moved":
       # TODO: Update cursor in Redis, trigger eviction logic
       pass
   ```

2. **Browser mode in WS** - Per task file, browser mode shouldn't use WS at all. Frontend synthesizes locally → calls `/tts/submit`. The `synthesis_mode` check in ws.py (line 242) is defensive only.

3. **test_client_tts.py** - Uses old HTTP flow. Two options:
   - Update to just test `/tts/submit` endpoint directly (browser TTS result submission)
   - Remove if `/tts/submit` is adequately tested elsewhere

4. **Frontend WS migration** - Major work remaining

5. **Delete HTTP `/synthesize`** - After frontend migrated

**Immediate Next Steps:**

1. Restart backend with new code ✅ (user doing)
2. Run tests to verify WS endpoint works
3. Fix any test failures
4. Then decide: cursor/eviction vs frontend WS client

---

## Migration Analysis: HTTP → WS Synthesis (UPDATED)

### Current State

**Backend - Ready for testing:**
- `ws.py`: Complete WS endpoint with all required functionality
- `audio.py`: Audio fetch ready
- `tts.py`: Legacy HTTP endpoint still exists (keep `/tts/submit` for browser mode)

**Tests - Migrated:**
- `test_tts.py`, `test_tts_billing.py`: Use WS
- `test_client_tts.py`: Still HTTP (browser TTS flow - may be valid)
- `conftest.py`: Has `TTSWebSocketClient` helper class

**Frontend - Still HTTP:**
- `PlaybackPage.tsx`: Uses HTTP long-polling
- No WS client yet

### Browser TTS Flow (Clarified)

Browser TTS **does not use WS for synthesis**:
1. Frontend generates job_id
2. Frontend synthesizes locally with Kokoro.js
3. Frontend calls `/tts/submit` with audio result
4. Backend caches audio

The `synthesis_mode` field in `WSSynthesizeRequest` exists for future flexibility, but current browser mode bypasses WS entirely.

### What's Left

| Task | Priority | Effort |
|------|----------|--------|
| Test WS endpoint e2e | High | Low |
| Cursor tracking + eviction | Medium | Medium |
| Frontend WS client | High | High |
| Delete HTTP `/synthesize` | Low | Low (after frontend) |
| Update `test_client_tts.py` | Low | Low |

### Tech Debt

1. **`useWS.ts` dead code** - Existing WS hook, could adapt for TTS
2. **Old model slugs in architecture.md** - Update after tests pass

---

## Session 2025-12-26 (continued) - Major Cleanup

### What Was Done

**Deleted:**
- `yapit/gateway/api/v1/tts.py` - entire file (legacy HTTP `/synthesize` endpoint)
- `yapit/gateway/processors/tts/client.py` - ClientProcessor class
- `tests/integration/test_client_tts.py` - tested obsolete flow
- `tests/yapit/gateway/processors/test_client_processor.py` - unit test for deleted class
- `get_client_processor`, `get_job`, `ClientProcessorDep`, `SynthesisJobDep` from deps.py
- Browser routes from `tts_processors.*.json`

**Added/Refactored:**
- `POST /v1/audio` in audio.py - simple browser TTS caching (no Future coordination)
  - Validates document ownership via `get_doc()`
  - Uses shared `get_model()`, `get_voice()` functions
  - 10MB max audio size
- Fixed `authenticate_ws` - proper WebSocket import (removed forward reference string)
- Stored `audio_cache` on `app.state` for WS access

**Key Learnings:**

1. **ClientProcessor was overengineered** - Used Future-based coordination for blocking HTTP. With WS architecture, browser TTS just needs simple caching endpoint.

2. **Dependency functions can be called directly** - `get_model(db, slug)`, `get_voice(db, m, v)`, `get_doc(id, db, user)` work without FastAPI's Depends wrapper.

3. **WebSocket deps need app.state access** - Can't use `request.app.state` in WS handlers, use `ws.app.state` directly.

### Test Failures - FIXED

Root causes found and fixed:
1. **`GET /v1/audio/{hash}` 500 error** - `get_block_variant` wasn't eagerly loading `variant.model`, causing `MissingGreenlet` when accessing lazy relationship outside session. Fixed by adding `selectinload(BlockVariant.model)`.

2. **"No status message received"** - Admin users were failing credit check. WS handler wasn't bypassing credit check for admins like HTTP did. Fixed by checking `user.server_metadata.is_admin`.

**All integration tests now pass.**

### TODO: Investigate

1. **Circular dependency in base.py** - `deps → manager → base → deps`. Currently broken with inline import. Check if we can restructure to avoid this.

2. **Document processor base classes** - Check if there are stale inheritance patterns that can be simplified now that ClientProcessor is gone.

3. **Test coverage review** - Scan all tests to identify:
   - Obsolete tests (testing deleted code)
   - Missing tests (new WS flow not covered)
   - Tests that can be simplified

4. **ws.py code duplication** - `_get_model_and_voice` and document ownership check duplicate logic from deps.py. Should refactor to use shared functions:
   - `get_doc(document_id, db, user)` for ownership check
   - `get_model(db, model_slug)` and `get_voice(db, model_slug, voice_slug)` for lookups
   - Challenge: WS needs different error handling (send WS message vs raise HTTPException)

### Immediate Next Steps

1. ✅ WS e2e flow works - integration tests pass
2. Frontend WS client migration (major work)
3. Or: refactor duplicated code in ws.py
4. Or: review document processor patterns

---

### 2025-12-27 - Test Coverage Review & Cleanup

**Session goal:** Review test coverage after WS migration, clean up unused code.

**Test coverage findings:**

Current integration tests (5 total):
- `test_tts.py` - Full WS synthesis flow (1 test, parametrized kokoro+higgs)
- `test_tts_billing.py` - 4 tests: insufficient credits, deduction, cache no-double-deduct, admin bypass

Deleted tests:
- `test_client_tts.py` - Tested old HTTP `/synthesize` + ClientProcessor
- `test_client_processor.py` - Unit test for deleted ClientProcessor

Missing: `POST /v1/audio` (browser TTS caching) has no tests.

**Code review findings:**

1. **ws.py duplication** - `_get_model_and_voice()` duplicates deps.py's `get_model()`/`get_voice()`. Document ownership check duplicates `get_doc()`. But duplication is ~20 lines, abstraction overhead not worth it. Leaving as-is.

2. **Unused `slug` param in TTS processors** - `TTSProcessorManager` passes `slug=f"{model}:{mode}"` but TTS processors never use `self._slug`. Only document processors use it. Should remove for TTS.

3. **Circular import in base.py** - `deps → manager → base → deps`. Fix: move `get_db_session` to db.py, `get_or_create_user_credits` to billing.py. Low priority, defer.

**Plan:**
1. Add basic test for `POST /v1/audio` (upload, cache check, reject oversized)
2. Remove unused `slug` param from TTS processor chain
3. Note circular import for later

**Security consideration (browser audio upload):**

User asked about DDOS/abuse risk with `POST /v1/audio` accepting 10MB uploads.

Attack vectors:
- Malicious user uploads garbage 10MB audio for every block in huge documents
- Storage/bandwidth costs, cache pollution

Mitigations to consider:
- **Rate limiting** - Per-user limit on audio submissions per minute/hour
- **Content validation** - Check audio headers (valid PCM/WAV), but attackers can fake these
- **Document size limits** - Cap blocks per document
- **Monitoring** - Track upload volume per user, alert on anomalies

Current stance: Not implementing now. Browser TTS is a nice-to-have feature, not critical path. If abuse happens, we'd notice via storage costs. Can add rate limiting reactively. The 10MB limit per block is already a constraint.

**Files modified:**
- `tests/integration/test_audio.py` (new) - Browser TTS endpoint tests (submit, retrieve, too-large, wrong-document)
- `yapit/gateway/processors/tts/base.py` - Removed `Processor` inheritance, stores `self._settings` directly
- `yapit/gateway/processors/tts/manager.py` - Removed slug param from `_create_processor`
- `yapit/gateway/processors/document/base.py` - Removed `Processor` inheritance, added `__init__` with settings/slug
- `yapit/gateway/processors/document/manager.py` - Inlined `ProcessorManager` logic (~30 lines, standalone)
- `yapit/gateway/processors/base.py` - DELETED (no longer needed)
- `~/.claude/plans/monitoring-observability-logging.md` - Added "Abuse Detection" section for audio upload monitoring

**Processor structure after refactor:**
```
processors/
├── document/
│   ├── base.py           # BaseDocumentProcessor (standalone, stores _settings + _slug)
│   ├── manager.py        # DocumentProcessorManager (standalone, loads JSON, dict by slug)
│   ├── mistral.py        # MistralOCRProcessor(BaseDocumentProcessor)
│   └── markitdown.py     # MarkitdownProcessor(BaseDocumentProcessor)
│
└── tts/
    ├── base.py           # BaseTTSProcessor (standalone, stores _settings + _model)
    ├── manager.py        # TTSProcessorManager (standalone, routes, background tasks)
    ├── local.py          # LocalProcessor(BaseTTSProcessor)
    └── runpod.py         # RunpodProcessor(BaseTTSProcessor)
```

No shared base classes between document and TTS - they have completely different purposes.

**Still TODO:**
- Frontend WS migration (separate task)

**Circular import fix (DONE):**
- Moved `get_or_create_user_credits` to db.py (re-exported from deps.py)
- `tts/base.py` now uses `create_session(self._settings)` directly instead of importing from deps.py
- No new abstractions needed - just use existing `create_session()`

**Open question for /archive:**
This task file grew too large - brainstorming/research should have been a separate task from implementation. Consider splitting when archiving.

### 2025-12-28 - Archiving

Task archived after backend implementation complete. Key knowledge extracted to `architecture.md`:
- TTS Architecture section rewritten (model/mode separation, WS flow, processors)
- Key Files Reference updated
- Tech debt section updated (frontend WS migration flagged)

Next work will be in separate task files:
- Frontend WS migration task (major)
- Prefetching optimization / batch mode UX task (after frontend is on WS)
