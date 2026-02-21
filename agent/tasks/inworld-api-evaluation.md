---
status: done
type: research
refs:
  - "[[inworld-tts]]"
---

# Task: Inworld.ai TTS API Evaluation

## Goal

Evaluate inworld.ai as potential premium TTS provider. Make informed decision on whether to integrate.

## Context

- Inworld.ai offers TTS at $5/1M characters (~$0.005/min)
- Free period: confirmed until **Dec 31, 2025**
- Alternative: Self-hosted HIGGS on RunPod (has cold start issues)

## Evaluation Criteria

### 1. Quality
- How does it sound compared to Kokoro?
- Voice variety - what voices are available?
- Naturalness for long-form reading (our use case)
- Handling of: punctuation, numbers, abbreviations, edge cases

### 2. Latency
- Time to first byte
- Streaming support?
- Consistency (does it spike?)
- Compare to Kokoro browser/server

### 3. Ease of Integration
- API design - RESTful? WebSocket? Both?
- Auth mechanism
- Error handling / rate limits
- SDK availability or just raw HTTP?
- Documentation quality

### 4. Pricing Deep Dive
- $5/1M characters - but what counts as a character?
- Spaces? Punctuation? Unicode?
- Any hidden fees (egress, requests, etc.)?
- Volume discounts?
- How does this translate to our per-minute pricing?

### 5. Business Viability
- How long has inworld.ai been around?
- Funding / stability?
- Is TTS their core product or side feature?
- Risk of API being deprecated / pricing changing?
- Terms of service - any usage restrictions for our use case?

### 6. Comparison to Alternatives
- vs RunPod HIGGS: cost, latency, ops burden
- vs other TTS APIs (ElevenLabs, Play.ht, etc.) if relevant
- What's the fallback if inworld.ai doesn't work out?

## Test Plan

1. Get API key (check if free trial still active)
2. Test with variety of content:
   - Short sentence
   - Long paragraph (academic paper style)
   - Text with numbers, abbreviations
   - Non-English text (if supported)
3. Measure latency (time to first byte, total time)
4. Subjective quality rating
5. Check available voices, pick best for our use case

## Open Questions

- ~~Is free period until Dec 25 or Dec 31?~~ **Confirmed: Dec 31, 2025**
- Voice aesthetic fit: 48+ voices available (professional, character types) - need to test for "cozy reading" fit
- Rate limits: Not documented anywhere. Unknown territory.
- Character counting: What exactly counts? Spaces? Punctuation? Unicode?
- WebSocket gateway charge ($2/1M chars) - does this apply to REST streaming or only WebSocket?

## Sources

**Official Docs:**
- https://docs.inworld.ai/docs/quickstart-tts - API quickstart
- https://docs.inworld.ai/docs/realtime/connect/websocket - WebSocket protocol
- https://docs.inworld.ai/api-reference/introduction - Auth methods
- https://docs.inworld.ai/docs/tts/voice-cloning - Voice cloning requirements
- https://docs.inworld.ai/docs/tts/best-practices/generating-speech - **summary**: recommends sentence-based chunking for latency; no specific char count
- https://docs.inworld.ai/docs/resources/rate-limits - Rate limits (20 req/sec per workspace)

**Marketing/Product:**
- https://inworld.ai/pricing - Pricing page
- https://inworld.ai/tts - Product landing page
- https://inworld.ai/blog/introducing-inworld-tts - Launch blog
- https://inworld.ai/blog/inworld-voice-2.0 - Voice 2.0 capabilities

**Technical:**
- https://arxiv.org/html/2507.21138v1 - **MUST READ** for audio architecture: TTS-1 technical report. Explains internal chunk consistency (decoder context extension), confirms no cross-request context mechanism. Also covers streaming latency, audio codec (X-codec2, 50 tokens/sec).
- https://github.com/inworld-ai/tts - MIT licensed training code
- https://inworld-ai.github.io/tts/ - Live demo with audio samples
- https://docs.aimlapi.com/api-references/speech-models/text-to-speech/inworld/tts-1-max - **summary**: max 500k chars per request

**Company Research:**
- Crunchbase, Tracxn, PitchBook for funding data

## Notes / Findings

### API Design

**REST Endpoints:**
- Sync: `POST https://api.inworld.ai/tts/v1/voice`
- Streaming: `POST https://api.inworld.ai/tts/v1/voice:stream`

**WebSocket (Realtime):**
- `wss://api.inworld.ai/api/v1/realtime/session?key=<session-id>&protocol=realtime`
- OpenAI Realtime-compatible event schema
- Audio via `response.output_audio.delta` events (base64 PCM16, 24kHz mono)

**Auth:** Basic Auth (base64-encoded API key) or JWT for client-side

**Request format:**
```json
{
  "text": "...",
  "voiceId": "Ashley",
  "modelId": "inworld-tts-1",
  "audio_config": {
    "audio_encoding": "LINEAR16",  // or "MP3"
    "sample_rate_hertz": 48000
  }
}
```

**Response:** JSON with `audioContent` (base64-encoded), streaming returns line-delimited JSON chunks

### Pricing Details

| Model | Price | Notes |
|-------|-------|-------|
| TTS-1 | $5/1M chars | 1.6B params, optimized for speed |
| TTS-1-Max | $10/1M chars | 8.8B params, highest quality |
| WebSocket Gateway | $2/1M chars | Unclear if applies to REST streaming |

- **Free until Dec 31, 2025** - no per-character charges
- 2M free characters for new users (beyond promo period)
- Zero-shot voice cloning: **free for all users**
- Volume discounts: not mentioned

### Technical Specs

- **Output:** 48kHz audio
- **Formats:** MP3, LINEAR16 (WAV), Opus
- **Latency:** Sub-250ms median (excluding network) - actual E2E will be higher
- **Languages:** 12 (EN, ES, FR, KO, NL, ZH, DE, IT, JA, PL, PT, RU) + Hindi/Arabic/Hebrew coming
- **Voices:** 48+ "Studio voices" across professional/character types
- **Voice cloning:** Zero-shot (5-15 sec audio) or Professional (30+ min, by request)
- **Emotion tags:** happy, sad, angry, surprised, fearful, disgusted
- **Delivery styles:** laughing, whispering
- **Non-verbal:** breathe, cough, laugh, sigh, yawn
- **Alignment:** Word-level and character-level timestamp support
- **Text limits:** Max 500,000 characters per request; docs recommend sentence-based chunking for latency
- **Cross-request context:** NOT supported. No API mechanism to pass audio tokens between requests for voice/prosody consistency (unlike HIGGS). Each request is independent. Internal chunk-to-chunk consistency (within single streaming request) is handled automatically via decoder context extension.

### Company Background

- **Founded:** 2021, Mountain View CA
- **Funding:** $117-120M total across 4 rounds
- **Valuation:** $500M (Aug 2023, latest public)
- **Investors:** Lightspeed, Microsoft M12, Eric Schmidt (First Spark), Stanford, Samsung, Intel, Kleiner Perkins, Founders Fund
- **Core business:** AI character engine for games/media - TTS is a **newer product (2024)**, not their core
- **Partnerships:** Logitech/Streamlabs (Jan 2025), LiveKit, Vapi

### Open Source

- **MIT licensed** TTS training code: https://github.com/inworld-ai/tts
- Uses SpeechLM architecture with SFT/RLHF training
- Dependencies: Python 3.10, CUDA 12.4/12.8, PyTorch 2.6+, Flash Attention
- Node.js SDK: `@inworld/web-core` on npm
- API examples repo: https://github.com/inworld-ai/inworld-api-examples

### Benchmark Claims

- "#1 on Artificial Analysis TTS Arena"
- "#1 on Hugging Face TTS Arena"
- Tested vs ElevenLabs, Cartesia, Hume AI - claims better WER and speaker similarity

### Yapit Fit Assessment

**Pros:**
- REST streaming endpoint fits our FastAPI backend well
- Very cheap ($5/1M vs ~$50/1M for ElevenLabs)
- Free trial period lets us evaluate thoroughly
- Timestamp alignment could enable better highlighting
- Simple Basic Auth, no complex OAuth
- Company well-funded, reasonable stability

**Cons/Concerns:**
- TTS is **not their core product** - risk of deprioritization, API changes
- Rate limits undocumented - unknown operational behavior under load
- Character counting rules unclear
- WebSocket gateway charge unclear (does REST streaming incur it?)
- Voices may not fit "cozy reading" aesthetic (more gaming/character-focused)
- 200ms latency is "median excluding networking" - actual E2E will be higher
- No SLA or uptime guarantees documented
- No cross-request audio context - each block synthesized independently (prosody won't "flow" between blocks like HIGGS context accumulation would enable)

---

## Work Log

### 2025-12-29 - Task Created

Context from earlier research:
- $5/1M chars pricing found on their website
- Claims "SOTA quality" and "20x cheaper than comparable models"
- Zero-shot voice cloning available
- API endpoint: `https://api.inworld.ai/tts/v1/voice`

Task created to do proper due diligence before committing to integration.

### 2025-12-29 - Documentation Research Complete

Sources reviewed and key findings summarized in Notes/Findings above. See Sources section for full list.

### 2025-12-29 - API Testing Complete

**Test setup:** API key obtained, ran streaming tests.

**Voice inventory:** 60 voices total across 11 languages (EN, ZH, NL, FR, DE, IT, JA, KO, PL, PT, ES, RU, HI)

**Latency results (streaming, ~300 char text):**

| Metric | Range | Notes |
|--------|-------|-------|
| Time to first byte | 440-1280ms | Varies by voice, ~500-700ms typical |
| Total time | 1.3-2.6s | For ~300 chars |

TTS-1-Max is significantly slower: 3000ms TTFB vs ~700ms for TTS-1.

**Best narrator voices for reading (my picks based on descriptions):**
- **Blake** - "Rich, intimate, perfect for audiobooks"
- **Luna** - "Calm, relaxing, meditation style"
- **Elizabeth** - "Professional, perfect for narrations"
- **Craig** - "British, refined and articulate"
- **Clive** - "British, calm and cordial"
- **Dennis** - "Smooth, calm and friendly"

**Fun voices:**
- **Hades** - "Commanding, gruff - omniscient narrator"
- **Dominus** - "Robotic villain"

**Customization:**
- Emotion tags work: `[happy]`, `[sad]`, `[whispering]`, etc.
- Different file sizes confirm they actually change the output
- Haven't tested speed control yet

**Samples generated:** `scripts/inworld_samples/`
- `narrator_*.mp3` - narrator voice comparison (book-style text)
- `content_*.mp3` - different content types (academic, numbers, edge cases)
- `emotion_*.mp3` - emotion tag tests
- `model_*.mp3` - TTS-1 vs TTS-1-Max comparison

**Waiting on:** User to listen to samples and provide quality feedback.

### 2025-12-29 - Additional Research & User Feedback

**Rate Limits (from docs.inworld.ai/docs/resources/rate-limits):**
- TTS: 20 requests/second per workspace
- "Usually sufficient for hundreds of concurrent users"
- Can request increases via Portal → Billing → "Increase rate limit"
- Response within 48 hours, increases at no additional cost

**Model Comparison (proper analysis):**

| Model | TTFB | Total Time (296 chars) | Audio Duration | Real-time Factor |
|-------|------|------------------------|----------------|------------------|
| TTS-1 | 500-1200ms | 1.7-2.1s | ~17-18s | 0.10-0.12x |
| TTS-1-Max | 1400-1700ms | 5.6-6.8s | ~18-23s | 0.30-0.34x |

TTS-1 generates audio 8-10x faster than real-time. TTS-1-Max is ~3x slower but still faster than real-time.

**Voice count clarification:**
- 60 total voices
- 25 English voices
- Docs saying "12 languages" was misread as "12 voices"

**Terms of Service (inworld.ai/terms):**
- License: "non-exclusive, non-transferable, non-sublicensable"
- Use: "internal business purposes"
- Output ownership: Assigned to you
- Training: Won't train on your non-public materials

The "internal business purposes" + "non-sublicensable" language is standard API boilerplate - means you can't resell API access itself, NOT that you can't build products. Evidence: they market to game devs, have scale pricing, integrate with LiveKit/Vapi. But could clarify with them if concerned.

**User voice feedback:**
- **Keep (all good):** Ashley, Blake, Carter, Clive, Craig, Dennis, Theodore, Wendy, Hades, Hana, Luna
- **Exclude:** Dominus (trash), Elizabeth (boring)
- Decision: Offer all voices in UI (except explicitly excluded)

**Next:** Figure out integration approach and billing model for profitability.

### 2025-12-29 - API Approach Analysis

**All Inworld TTS API options:**

| Method | Endpoint | Use Case | Latency Profile |
|--------|----------|----------|-----------------|
| **REST sync** | `POST /tts/v1/voice` | Simple one-shot, batch | Wait for full audio |
| **REST streaming** | `POST /tts/v1/voice:stream` | Real-time with HTTP | TTFB ~500-700ms, chunks arrive as generated |
| **WebSocket** | `wss://...` | Conversational AI, barge-in | Persistent connection, lowest latency for multi-turn |
| **gRPC** | via SDK | Game engines (Unity) | Lower serialization overhead, optional |

**Decision: REST streaming is best for Yapit.**

Rationale:
1. **Yapit is document reading, not conversational** - we don't need barge-in, multi-context, or persistent connections
2. **One request per block** - matches our existing architecture perfectly
3. **Simple implementation** - just HTTP POST, no WebSocket connection management
4. **Already tested** - our test scripts used REST streaming successfully (500-700ms TTFB)

WebSocket advantages (multi-context, interruption handling, streaming LLM output) don't apply to our use case. We synthesize discrete text blocks, not real-time conversation.

**Voice JSON:** Saved to `yapit/data/inworld/voices.json` (60 voices, all languages)

### 2025-12-30 - Sync vs Streaming Deep Dive

Comprehensive testing with 8 different text types (short, medium, long, academic, numbers, LaTeX, random, unicode):

| Text Length | Sync | Stream | Difference |
|-------------|------|--------|------------|
| Short (38 chars) | 735ms | 731ms | ~equal |
| Medium (100-220 chars) | 1.7-2.3s | 1.2-1.4s | **26-38% faster** |
| Long (400-450 chars) | 3.4-3.5s | 2.4-2.6s | **26-31% faster** |
| Very long (700 chars) | 3.5s | 3.6s | ~equal |

**Finding:** Streaming is genuinely faster for medium-length text (100-450 chars) - exactly typical block sizes. Average difference across all tests: **+23.3%** in favor of streaming.

The docs saying "sync might be faster" only applies to very short or very long texts. For typical paragraph-sized content, streaming wins.

**Decision confirmed:** Use REST streaming endpoint (`/tts/v1/voice:stream`)

### 2025-12-30 - Backend Implementation Complete

**Files created/modified:**
- `yapit/gateway/processors/tts/inworld.py` - InworldProcessor class (~75 lines)
- `yapit/data/inworld/voices.json` - 60 voices across 13 languages
- `tts_processors.dev.json` - Added `inworld` and `inworld-max` model configs
- `yapit/gateway/dev_seed.py` - Loads Inworld voices for both models
- `tests/integration/test_tts.py` - Added inworld test case with `@pytest.mark.inworld`
- `pyproject.toml` - Added `inworld` pytest marker

**Models configured:**
- `inworld` → TTS-1 ($5/1M chars, faster)
- `inworld-max` → TTS-1-Max ($10/1M chars, higher quality)

**To test:** Run with `-m inworld` marker when INWORLD_API_KEY is set.

**Remaining for frontend task:**
- Model picker UI to show Inworld models
- Voice picker to display 60 Inworld voices
- Pricing display in UI
