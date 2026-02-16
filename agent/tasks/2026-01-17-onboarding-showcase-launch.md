---
status: done
started: 2026-01-17
---

# Task: Onboarding & Showcase for Launch

## Intent

Make Yapit demonstrate value immediately for all users, regardless of device or signup status:

- **Has WebGPU:** Works immediately with local Kokoro, no friction, no signup required
- **No WebGPU + no paid plan:** Same UI, but proactive banner explains limitations and points to showcase docs
- **Has paid plan:** Full cloud synthesis, all features work

Key principle: Users who can use free local TTS should never be pressured to sign up. Users without WebGPU need a paid plan for cloud synthesis — technical requirement, not business gate. But they can still try cached showcase content for free.

## Goals

1. ~~**Bug fix:** Usage check must only count uncached blocks~~ — **DONE** in [[2026-01-14-pricing-restructure]]
2. **Showcase docs:** Seed new users with clones + "Getting Started" section on dashboard
3. **Voice previews:** Play button in voice picker (cycling through variety sentences)
4. **Cache warming:** Systemd timer to keep showcase + previews hot
5. **WebGPU warning banner:** Proactive messaging for users who can't synthesize locally
6. **UI unlock:** Remove subscription gating on premium voice tabs

## Non-Goals

- Premium voice signup credits — users can try premium voices via cached showcase content and voice previews; using premium on their own content requires subscription
- Cloud Kokoro signup bonus (depends on [[rate-limiting]], not yet implemented)
- Public document library
- AI document transformation showcase (not stable enough yet)

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

**Dashboard "Getting Started" section:**
- Shows showcase doc links for new/guest users
- Dismissible (localStorage) for users who don't want it
- Same links available on /tips page permanently

## Voice Previews

**Variety sentences** (cycled on each click, shows voice in different contexts):
1. "Hello, this is a sample of my voice."
2. "The quick brown fox jumps over the lazy dog."
3. "I can read documents, articles, and research papers."
4. "Sometimes I wonder what it would be like to have a body."
5. "Breaking news: scientists discover that coffee is, in fact, essential."

**UI:** Small play button in voice picker rows (next to star icon). Each click plays next sentence in cycle.

**Cache:** All 5 sentences × all voices pre-synthesized via cache warming job

## Cache Warming

**Systemd timer (daily):**
1. Request all 5 voice preview sentences for each voice (~50 voices × 5 = 250 requests)
2. Request each showcase doc block for each voice in `cache_voices` from config

**Reads from:** `showcase.json` for doc UUIDs and which voices to warm

**Cost:** Near-zero after initial synthesis (~$0.02 for Inworld voices one-time)

**Purpose:** Ensures showcase content and voice previews stay in cache, never evicted

## UI: Unlock Premium Voice Tabs

**Current:** Inworld tab locked behind `canUseInworld` subscription check in `voicePicker.tsx`

**Change:**
- All voice tabs accessible to all users
- On synthesis request for uncached content: if insufficient credits → show modal
- Cached content plays free regardless of tier

This enables anonymous users to try premium voices on showcase content.

## Self-Hosting: Unlimited Credits When Billing Disabled

**Context:** Backend has `BILLING_ENABLED` env var. When `false`, billing checks are bypassed in code, but frontend still shows locked features because user has no subscription.

**Cleaner approach:** Instead of conditional logic everywhere, seed a "self-hosted" subscription with effectively infinite limits.

**Implementation:**
- On startup (or user creation), if `BILLING_ENABLED=false`:
  - Create/upsert a "Self-Hosted" plan with huge limits (e.g., 999,999,999 chars/tokens)
  - Auto-assign this plan to users (no Stripe customer/subscription IDs needed)
- Same code paths run — billing checks pass because limits are huge
- Frontend sees a subscribed user with massive quotas — no special handling needed
- No subscription prompts, no locked features, no conditional UI logic

**Why better:**
- Single code path (no `if billing_enabled` branches scattered around frontend)
- Frontend already handles displaying usage/limits — just shows huge numbers
- Cleaner than frontend checking a config flag and conditionally unlocking things

## WebGPU Warning Banner

**Condition:** `!hasWebGPU && !hasPaidPlan`

Show proactive banner at top of document view (using existing error banner primitive):

> "Your device may not support free local processing. [Try showcase examples] for free, or [get a plan] for cloud access."

- Permanently dismissible via "Don't show again" (localStorage)
- Sign-in status doesn't matter — it's about "can you synthesize?"
- Users can still try — maybe WASM works, maybe content is cached
- Banner sets expectations without blocking

**Detection:**
```typescript
const hasWebGPU = !!navigator.gpu;
const hasPaidPlan = subscription?.tier !== 'free';
const showWebGPUWarning = !hasWebGPU && !hasPaidPlan;
```

## Dependencies

- [[rate-limiting]] — Cloud Kokoro signup bonus blocked until rate limiting exists

## Key Files

| File | Change |
|------|--------|
| `yapit/gateway/api/v1/webhooks.py` | New: Stack Auth webhook endpoint for user.created |
| `showcase.json` | New: Config for showcase doc UUIDs and cache voices |
| `scripts/warm_cache.py` | New: Cache warming script (run by systemd timer) |
| `frontend/src/components/voicePicker.tsx` | Unlock tabs, add preview button with cycling sentences |
| `frontend/src/components/WebGPUWarningBanner.tsx` | New: Proactive warning for no-WebGPU + no-plan users |
| `frontend/src/hooks/useWebGPU.ts` | New: WebGPU detection hook |
| `frontend/src/pages/TextInputPage.tsx` | Add "Getting Started" showcase section |
| `frontend/src/pages/TipsPage.tsx` | Add showcase doc share links |
| `frontend/src/pages/DocumentViewPage.tsx` | Show WebGPU warning banner |

## Sources

**Knowledge files:**
- [[tts-flow]] — Cache mechanics, variant hashing (text-based, not doc-based)
- [[auth]] — Anonymous user handling
- [[rate-limiting]] — Dependency for cloud kokoro signup bonus

**External docs:**
- Reference: [Stack Auth webhooks](https://docs.stack-auth.com/docs/next/concepts/webhooks) — Supports user.created events
- Reference: [MDN navigator.gpu](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/gpu) — Returns undefined on unsupported browsers
- Reference: [Inworld pricing](https://inworld.ai/pricing) — $5/1M chars for TTS-1
