---
status: active
started: 2026-01-17
---

# Task: Onboarding & Showcase for Launch

## Intent

Make Yapit demonstrate value immediately for all users, regardless of device or signup status:

- **Desktop with WebGPU:** Works immediately with local Kokoro, no friction, no signup required
- **Desktop without WebGPU:** Works (slower via WASM), hint at cloud option if synthesis is slow
- **Mobile (not signed in):** Showcase dashboard with pre-cached content, signup CTA
- **Mobile (signed in):** Normal experience, full functionality

Key principle: Users who can use free local TTS should never be pressured to sign up. Mobile users need signup because local TTS doesn't work there — technical requirement, not business gate.

## Goals

1. **Bug fix:** Usage check must only count uncached blocks
2. **Showcase docs:** Seed new users with 5 curated document clones
3. **Voice previews:** Play button in voice picker (standard sentence per voice)
4. **Cache warming:** Systemd timer to keep showcase + previews hot
5. **Mobile guest experience:** Special dashboard showing only showcase docs
6. **UI unlock:** Remove subscription gating on premium voice tabs

## Non-Goals

- Premium voice signup credits — users can try premium voices via cached showcase content and voice previews; using premium on their own content requires subscription
- Cloud Kokoro signup bonus (depends on [[rate-limiting]], not yet implemented)
- Public document library
- AI document transformation showcase (not stable enough yet)

## Bug Fix: Usage Check Before Cache

**Moved to [[2026-01-14-pricing-restructure]]** — being fixed there as part of the 3-tier usage waterfall implementation (subscription → rollover → purchased). The fix requires knowing which blocks are uncached before checking/decrementing usage pools.

## Showcase Documents

**Content (3-5 docs demonstrating core features):**
1. Popular blog post URL — shows URL → TTS works
2. PDF with figures/math — shows AI extraction, alt text generation
3. Image — shows image → text capability
4. Short Wikipedia article — familiar content, quality demo

**Source documents:**
- Create with admin/personal account, mark `is_public=true`
- UUIDs don't expose account identity (no social features)

**Config file (`showcase.json`):**
```json
{
  "documents": [
    {"uuid": "...", "description": "Blog post example"},
    {"uuid": "...", "description": "PDF with figures"}
  ],
  "cache_voices": ["af_heart", "ashley", "af_sky"]
}
```
Used by both signup cloning and cache warming script.

**On signup (Stack Auth webhook):**
- Receive `user.created` event at `POST /v1/webhooks/stack-auth`
- Clone showcase docs to new user's library (reuse existing sharing/clone logic)
- Docs become normal documents in their library — fully deletable, no special handling

**Tips page:**
- Include share links to showcase docs
- If user deleted one and wants it back → click link → re-imports

**Mobile guest experience:**
- Detect: mobile screen + no WebGPU + not signed in
- Show: special dashboard with only showcase docs, no text input field
- CTA: "Sign up to use your own URLs, documents, and text"

## Voice Previews

**Standard sentence:** "Hello, this is a sample of my voice. I can read documents, articles, and more."

**UI:** Small play button in voice picker rows (next to star icon)

**Cache:** Pre-synthesized for ALL voices as part of cache warming job

## Cache Warming

**Systemd timer (daily):**
1. Request voice preview sentence for each voice (~50 voices)
2. Request each showcase doc block for each voice in `cache_voices` from config

**Reads from:** `showcase.json` for doc UUIDs and which voices to warm

**Cost:** Near-zero after initial synthesis (~$0.02 for Inworld voices one-time)

**Purpose:** Ensures showcase content and voice previews stay in cache, never evicted

## UI: Unlock Premium Voice Tabs

**Current:** Inworld tab locked behind `canUseInworld` subscription check in `voicePicker.tsx`

**Change:**
- All voice tabs accessible to all users
- On synthesis request for uncached content: if insufficient credits → show modal
- Cached content plays free regardless of tier (with bug fix above)

This enables anonymous users to try premium voices on showcase content.

## Mobile Detection

```typescript
const isMobile = useIsMobile(); // screen width < 768
const hasWebGPU = !!navigator.gpu;
const isSignedIn = !!user;

// Show showcase-only dashboard
const showShowcaseDashboard = isMobile && !hasWebGPU && !isSignedIn;
```

**Desktop without WebGPU — slowness hint:**
- Threshold: 15 seconds for first block (can tune down later)
- Permanently dismissible via "Don't show again" (localStorage)
- Message: "Your system might not support local inference. [Learn more]"
- Learn more → links to help section explaining WebGPU requirements and how to check support
- If dismissed, never shows again for that browser

## Dependencies

- [[rate-limiting]] — Cloud Kokoro signup bonus blocked until rate limiting exists

## Key Files

| File | Change |
|------|--------|
| `yapit/gateway/api/v1/webhooks.py` | New: Stack Auth webhook endpoint for user.created |
| `showcase.json` | New: Config for showcase doc UUIDs and cache voices |
| `scripts/warm_cache.py` | New: Cache warming script (run by systemd timer) |
| `frontend/src/components/voicePicker.tsx` | Unlock tabs, add preview button |
| `frontend/src/hooks/use-mobile.ts` | Add WebGPU detection |
| `frontend/src/pages/TextInputPage.tsx` | Conditional showcase dashboard for mobile guests |
| `frontend/src/pages/TipsPage.tsx` | Add showcase doc share links |

## Open Questions

1. **Slowness hint threshold:** Starting with 15 seconds, may tune down based on feedback.

## Sources

**Knowledge files:**
- [[tts-flow]] — Cache mechanics, variant hashing (text-based, not doc-based)
- [[auth]] — Anonymous user handling
- [[rate-limiting]] — Dependency for cloud kokoro signup bonus

**External docs:**
- Reference: [Stack Auth webhooks](https://docs.stack-auth.com/docs/next/concepts/webhooks) — Supports user.created events
- Reference: [MDN navigator.gpu](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/gpu) — Returns undefined on unsupported browsers
- Reference: [Inworld pricing](https://inworld.ai/pricing) — $5/1M chars for TTS-1
