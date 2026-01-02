---
status: done
type: implementation
---

# Task: Model & Voice Picker Redesign

## Goal

Redesign the voice picker to:
1. Support ALL Kokoro voices (all languages, not just current subset)
2. Present voices cleanly without overwhelming UI
3. Integrate with premium model strategy (API vs self-hosted)

## Design Context

**Current state:**
- Voice picker exists with Kokoro (28 voices) and HIGGS tabs
- Pinning system for favorites
- localStorage persistence
- Toggle says "Browser" / "Server" (technical terms, not consumer-friendly)

**Design tension:**
- Open source / self-hostable = configurability, choice
- Apple-style = "just works", minimal tuning needed
- Need to balance both

**Product philosophy:**
- Open source = net benefit for the world, genuinely good free tier
- If you have capable hardware, browser TTS should be great (not crippled)
- Premium exists for unique value (quality, convenience), not to extract money from everyone
- Okay if many users thrive on free - that drives adoption
- Not a "freemium trap" - genuine value at each tier

**Voice organization ideas:**
- Group by language
- Highest quality voices at top
- Gender grouping (fewer male voices, generally lower quality)
- Pinning/favorites for quick access

## UI States to Handle

**From architecture.md:**
> UI stuff for when you dont have enough credits, and so on. Generally the whole ui picker with instead of "server / browser" have "free / pro/premium" and greying out voices you cant use, stuff like that.

**States to design for:**
1. Not logged in
2. Logged in, no credits
3. Logged in, has credits
4. Insufficient credits for specific tier

**Design work (agent responsibility):**
- Propose UI treatment for each state (greyed out is just one option - could be badges, overlays, subtle indicators, upgrade prompts, etc.)
- Propose terminology (Free/Premium, or something else entirely)
- Create mockups/prototypes for user feedback
- User reacts with "fits the vision" or "doesn't work" - design decisions are mine to make

**The Kokoro model tier question:**
Same model (Kokoro) can run in browser OR on our server. Why pay for server if you have fast GPU locally?

Possible reasoning for server Kokoro:
- Convenience (no device resource usage, instant if cached)
- Reliability (server consistent, browser WASM flaky on some devices)
- Speed (browser WASM slow on most devices)

Pricing implication:
- Server Kokoro = very cheap (just CPU time, "1 credit = 1 second"?)
- Premium models (HIGGS, API) = more expensive (GPU, higher quality)

So potentially 3 tiers:
1. **Free** - Browser Kokoro (your device does the work)
2. **Cheap** - Server Kokoro (our CPUs, same quality, faster/reliable)
3. **Premium** - HIGGS/API (better quality, GPU, higher cost)

## Phase 1: Kokoro Voice Inventory

**First step:** Check what voices are actually available.

Sources to check:
- HuggingFace repo (voices.json or similar)
- GitHub repo for Kokoro
- Current implementation (what subset are we using?)

**Questions:**
- How many total voices?
- Which languages?
- Quality tiers within voices?
- Any metadata (gender, style, quality rating)?

## Phase 2: Premium Model Strategy

**The bigger question:** What's our premium model situation?

**Options:**
1. **Self-hosted HIGGS on RunPod** - We control it, variable cost, cold start issues
2. **API model (inworld.ai or similar)** - $5/million tokens, managed, potentially faster
3. **Both** - Self-hosted + API overflow/backup
4. **Just API** - Simpler ops, pay per use

**Economics to research:**
- inworld.ai: $5/million tokens → cost per character?
- RunPod HIGGS: what's actual cost at our expected usage?
- Cold start latency comparison
- Quality comparison (if we can test both)

**This affects voice picker because:**
- If 2 models: Kokoro (free) + one premium
- If 3 models: Kokoro (free) + self-hosted premium + API premium
- UI needs to reflect available models and their cost implications

## Dependencies

**Credits system needs to be working first.**
The voice picker UI states (greyed out, insufficient credits, etc.) depend on having a working credits system. User may tackle credits before fully implementing the picker redesign.

## Open Questions

1. What's the full Kokoro voice inventory? (research needed)
2. API model (inworld.ai) vs RunPod HIGGS economics?
3. Do we want 2 or 3 model tiers?
4. How to present "free vs premium" in UI without being pushy?
5. Group by language first, or by quality/popularity?
6. What should happen when user lacks credits? Grey out? Prompt? Redirect?
7. "Free" / "Premium" vs other terminology?

**Mode:** Agent researches and proposes answers with prototypes → user reacts → iterate

## Notes / Findings

### Kokoro Voice Inventory (2025-12-29)

**Source:** [VOICES.md on HuggingFace](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)

**Total available:** 58 voices across 9 languages
**Currently implemented:** 28 voices (English only)
**Missing:** 30 voices in 7 languages

| Language | Code | Female | Male | Total | Quality |
|----------|------|--------|------|-------|---------|
| American English | a | 11 | 9 | 20 | ✅ Best (A to F+) |
| British English | b | 4 | 4 | 8 | Good (B- to D) |
| Japanese | j | 4 | 1 | 5 | Medium (C- to C+) |
| Mandarin Chinese | z | 4 | 4 | 8 | Low (all D) |
| Spanish | e | 1 | 2 | 3 | No grades listed |
| French | f | 1 | 0 | 1 | Good (B-) |
| Hindi | h | 2 | 2 | 4 | Medium (C) |
| Italian | i | 1 | 1 | 2 | Medium (C) |
| Brazilian Portuguese | p | 1 | 2 | 3 | No grades listed |

**Top quality voices (A/B tier):**
- af_heart (A) - American Female ⭐
- af_bella (A-) - American Female
- af_nicole (B-) - American Female
- bf_emma (B-) - British Female
- ff_siwis (B-) - French Female

**Observations:**
- Male voices max out at C+ quality
- Non-English support described as "thin" due to weak G2P and limited training data
- French has only 1 voice but it's B- quality
- Chinese voices all D-grade

**Implementation notes:**
- Current `KokoroVoice` type only has `"en-us" | "en-gb"` for language
- Need to extend to support all 9 language codes
- Grouping function `groupKokoroVoices()` hardcoded for English only

### Premium Model Economics (2025-12-29)

**Inworld.ai TTS API:**
- **$5 per 1 million characters** ([source](https://inworld.ai/pricing))
- ~1000 chars ≈ 1 min audio → **~$0.005/min**
- Free through Dec 31, 2025
- Zero-shot voice cloning free
- Claims "20x cheaper than comparable models"
- Managed infrastructure, no cold starts

**RunPod Serverless (fresh data from [runpod.io/pricing](https://www.runpod.io/pricing)):**
- A100 80GB: ~$2.17-2.72/hr (active vs flex)
- H100: ~$3.35-4.18/hr
- RTX 3090: ~$0.31/hr (if available)
- HIGGS synthesis speed: needs testing
- Cold start latency: problem for serverless

**Note:** Old billing-pricing-strategy.md may be stale - rethinking pricing from ground up.

**Key trade-offs for premium model decision:**

| Inworld.ai | RunPod HIGGS |
|-----------|--------------|
| $5/1M chars (~$0.005/min) | Variable (GPU + synthesis speed) |
| No cold starts | Cold starts problematic |
| Zero ops | Self-managed |
| Claims SOTA quality | Quality unknown |
| Free through Dec '25 | Costs now |

**What we actually need to decide:**
1. Test inworld.ai quality during free period
2. Test HIGGS latency/quality if we want self-hosted option
3. Pricing model needs fresh thinking (credits vs subscription vs hybrid)
4. Can offer both? API as primary, self-hosted as fallback?

---

## Work Log

### 2025-12-29 - Task Created

**User's direction:**
- Support all Kokoro voices (all languages from HuggingFace/GitHub)
- Clean UI, not overwhelming, but full choice available
- Pinning system exists, could be improved
- Group by language, quality at top, consider gender grouping
- Male voices fewer + lower quality, don't put at forefront
- Apple-style simplicity but open source flexibility

**Integration with premium model:**
- Need to factor in whether we use API model, self-hosted, or both
- inworld.ai @ $5/million tokens as alternative to RunPod HIGGS
- Brainstorm economics before finalizing picker design
- Model picker design depends on how many models we're offering

**Additional context from user:**
- Need to handle UI states: not logged in, no credits, insufficient credits
- Current "Browser" / "Server" terminology not consumer-friendly → "Free" / "Premium"
- Grey out unavailable voices, show costs, etc.
- Credits system is a dependency — may need to fix that first
- Referenced architecture.md note about picker UI improvements

**Status:** Phase 1 complete. Remaining work blocked on credits system and pricing decisions.

### What's Done
- ✅ All 58 Kokoro voices added (9 languages)
- ✅ Language-based collapsible sections with flags
- ✅ Quality sorting within languages
- ✅ ✨ sparkle for A/B tier, ♀/♂ gender indicators
- ✅ Starred voices show language flag
- ✅ Playback bug fixed (short documents)

### What's Remaining (Blocked)
- Premium model integration (needs inworld.ai evaluation)
- Free/Premium terminology (needs pricing strategy)
- UI states for no credits / insufficient credits (needs credits system)
- Mobile: should browser TTS be hidden? (needs credits/signup flow discussion)

### 2025-12-29 - Kokoro Voice Expansion Implementation

**Changes made:**

Frontend (`frontend/src/lib/voiceSelection.ts`):
- Added all 58 Kokoro voices (was 28)
- New `KokoroLanguageCode` type with 9 languages
- `LANGUAGE_INFO` with labels and flag emojis
- `groupKokoroVoicesByLanguage()` for language-based grouping
- `isHighQualityVoice()` for A/B tier detection
- Voices sorted by quality within each language group

Frontend (`frontend/src/components/voicePicker.tsx`):
- Collapsible language sections (English expanded by default)
- Flag emoji + voice count per language
- ✨ sparkle for high quality voices (distinct from ⭐ starred)
- ♀/♂ gender indicators
- Renamed "Pinned" to "Starred" for consistency

Backend (`yapit/workers/kokoro/voices.json`):
- Added all 58 voices with proper language codes (ja, zh, es, fr, hi, it, pt-br)

**User feedback incorporated:**
- Star = starred/pinned (yellow when active)
- Sparkle = high quality indicator (avoids confusion)
- Gender symbols better than grouping
- Removed "📌 Pinned" emoji, just "Starred"

**Note:** Backend restart needed to seed new voices. Frontend can be tested immediately.

### 2025-12-29 - Research Session

**Completed:**
1. ✅ Kokoro voice inventory - 58 voices, currently only 28 (English) implemented
2. ✅ Inworld.ai pricing research - $5/1M chars, free through Dec '25
3. ✅ RunPod pricing checked - varies by GPU

**Key findings:**
- 30 more Kokoro voices to add (Japanese, Chinese, Spanish, French, Hindi, Italian, Portuguese)
- Current code (`voiceSelection.ts`) hardcoded for English only
- Inworld.ai looks promising for premium (cheap, no cold starts, free to test now)
- Pricing strategy needs ground-up rethink (old billing doc may be stale)

**Blocked on:**
- Premium model decision: inworld.ai vs HIGGS vs both?
- Pricing model: credits vs subscription vs hybrid?
- Credits system needs to work before picker can show "you can't afford this"

**Could proceed with:**
- Adding missing Kokoro voices (pure implementation, no decisions needed)
- UI grouping by language (independent of premium model question)
