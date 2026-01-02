---
status: done
type: implementation
---

# Task: Inworld Frontend Integration

Related: [[inworld-api-evaluation]], [[pricing-strategy-rethink]]

Read [[pricing-strategy-rethink]] for context on premium features and billing strategy - affects how we present model/voice options.

## Goal

Add Inworld to voice picker, make it work end-to-end.

## Scope

- Add Inworld tab (like Kokoro/HIGGS tabs)
- Both `inworld` and `inworld-max` models
- Fetch voices from API (`GET /v1/models`) instead of hardcoding
- Show voice descriptions in UI
- Group by language (like Kokoro)
- Manual voice categorization (narrative, character, etc.) - decide during implementation

## Browser Kokoro Voice Limitation

The ONNX model (`Kokoro-82M-v1.0-ONNX`) only includes 28 English voices (American + British). Non-English voices (Japanese, Spanish, etc.) are **not available** in browser mode - this is a real technical limitation, not artificial.

**UI approach:** Non-English voices should be greyed out / disabled in browser mode with a tooltip explaining they require server mode (premium). This aligns with [[pricing-strategy-rethink]] - free tier = browser TTS with English voices, paid = server TTS with all voices + Inworld/HIGGS.

## Out of Scope

- Model picker redesign
- Billing/pricing display
- Those are separate tasks

## Open Questions

~~How to differentiate inworld vs inworld-max in UI?~~ **Resolved:** Toggle button at top of Inworld tab (TTS-1 / TTS-1-Max), similar to Kokoro's Browser/Server toggle.

---

## Work Log

### 2025-12-30 - Task Created

Backend done in [[inworld-api-evaluation]]. 60 voices, 13 languages.

Checked browser Kokoro - all 55 voices already available, no fix needed. One model loads, voices are just parameters.

### 2025-12-30 - Frontend Implementation Complete

**Files created:**
- `frontend/src/hooks/useInworldVoices.ts` - Hook to fetch Inworld voices from API with caching

**Files modified:**
- `frontend/src/lib/voiceSelection.ts` - Added Inworld types (`InworldVoice`, `InworldLanguageCode`), language info for 13 languages, `groupInworldVoicesByLanguage()` function, updated `ModelType` to include `"inworld" | "inworld-max"`
- `frontend/src/components/voicePicker.tsx` - Added Inworld tab with quality toggle (TTS-1/TTS-1-Max), voice list grouped by language, descriptions displayed

**Implementation decisions:**
- Used toggle button for TTS-1 vs TTS-1-Max (not separate tabs) - keeps UI simple, consistent with Kokoro's Browser/Server toggle
- Fetched voices from API (`GET /v1/models/inworld/voices`) - no auth required for this endpoint
- Cached voices in module scope to avoid refetching
- Grouped by language with English expanded by default
- Voice descriptions shown as secondary text in voice rows
- Starring/pinning works across all model tabs (shared localStorage)

**Verified via Chrome DevTools MCP:**
- ✅ Inworld tab appears between Kokoro and HIGGS
- ✅ Quality toggle switches between "Inworld" and "Inworld Max" display
- ✅ 60 voices load from API across 13 languages
- ✅ Voice descriptions display correctly
- ✅ Language collapsible sections work
- ✅ Starring voices works with flag in starred section
- ✅ Build passes with no errors

**Not implemented (out of scope per task file):**
- Manual voice categorization (narrative, character, etc.) - decided against this for now, descriptions are sufficient
- Browser Kokoro non-English voice greying - separate task, affects Kokoro tab not Inworld

### 2025-12-30 - Bug Fix: Static Noise on Inworld Playback

**Issue:** Inworld audio played as static noise instead of speech.

**Root cause:** `PlaybackPage.tsx:fetchAudioFromUrl()` assumed all server audio was raw PCM (Int16), but Inworld returns MP3. Interpreting MP3 bytes as raw PCM samples produces noise.

**Initial attempt:** Checked `x-audio-codec` custom header - failed because axios doesn't expose custom headers via bracket notation.

**Working fix:** Check standard `content-type` header instead:
```typescript
const contentType = response.headers["content-type"] || "";
const isMP3 = contentType.includes("mp3");

if (isMP3) {
  // MP3 (Inworld): use browser's built-in decoder
  audioBuffer = await audioContextRef.current.decodeAudioData(response.data.slice(0));
} else {
  // Raw PCM (Kokoro/HIGGS): convert Int16 to Float32
}
```

Note: `.slice(0)` creates a copy because `decodeAudioData` detaches the ArrayBuffer.

**File modified:** `frontend/src/pages/PlaybackPage.tsx`

### 2025-12-30 - Polish: Sort Languages by Speaker Count

Updated language display order for both Kokoro and Inworld to sort by global speaker count instead of alphabetically.

**Kokoro order:** American English → British English → Chinese → Hindi → Spanish → French → Portuguese → Japanese → Italian

**Inworld order:** English → Chinese → Hindi → Spanish → French → Portuguese → Russian → Japanese → German → Korean → Italian → Polish → Dutch

**File modified:** `frontend/src/lib/voiceSelection.ts`
