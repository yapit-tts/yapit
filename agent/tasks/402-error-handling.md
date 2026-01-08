---
status: done
started: 2026-01-03
completed: 2026-01-08
---

# Task: 402 Payment Required Error Handling

Related: [[voice-picker-improvements]] (UI gating for free users)

## Problem

When subscribed user depletes their quota mid-session, backend returns 402. Currently shows raw technical error message in small red text. Confusing UX.

## Current Behavior

1. Backend sends: `{"type": "error", "error": "Usage limit exceeded for server_kokoro: limit 100000, used 99500, requested 1000, remaining 500"}`
2. Frontend shows raw message in small red text near voice picker
3. Playback stops, no clear next step

## Decided UX

**On quota exceeded → Show modal:**
> "You've reached your Cloud voice quota for this month."
>
> [Continue with Local] [Upgrade Plan]

- "Continue with Local" → switches to browser TTS, playback continues
- "Upgrade Plan" → navigates to `/subscription`

**Progress bar warning:**
- At 95%+ quota usage, sidebar "Plan" button progress bar turns brownish/amber
- Visual heads-up before hitting the wall

**Deferred:**
- Whether to show characters vs hours in quota display (keep hours for now)

## Files

- `frontend/src/hooks/useTTSWebSocket.ts` — receives error, sets `connectionError` (line 135-137)
- `frontend/src/components/soundControl.tsx` — displays error (lines 611-615, 672-676)
- `frontend/src/components/sidebar.tsx` (or wherever Plan button lives) — progress bar color
- `yapit/gateway/exceptions.py` — `UsageLimitExceededError` with structured data

## Implementation Notes

**Detecting quota error:**
```tsx
const isQuotaExceeded = connectionError?.includes("Usage limit exceeded");
```

**Modal component:**
- Could use existing Dialog/AlertDialog from shadcn
- State: `showQuotaModal: boolean`
- On "Continue with Local": call voice picker's toggle to switch to `kokoro` model

**Progress bar color:**
- Need to know current usage percentage
- Either from subscription endpoint or track locally
- At 95%+, apply brownish color class to progress bar

## Testing Instructions

Test with the dev user by manipulating the database directly:

1. **Set up Plus plan with 95% usage:**
   ```sql
   -- Give dev user a Plus plan (or update existing subscription)
   -- Set usage to ~95% of limit to test warning state
   UPDATE usageperiod SET server_kokoro_characters = <95% of limit> WHERE user_id = '<dev_user_id>';
   ```

2. **Verify warning state (interactive with user):**
   - Progress bar in sidebar should turn brownish/amber
   - User confirms: "Yes, this looks right for 95% usage"

3. **Test playback at 95%:**
   - Play a short document with Cloud mode
   - Should still work (quota not exceeded yet)

4. **Set usage to 100% (or over):**
   ```sql
   UPDATE usageperiod SET server_kokoro_characters = <at or over limit> WHERE user_id = '<dev_user_id>';
   ```

5. **Verify modal appears (interactive with user):**
   - Try to play with Cloud mode
   - Modal should appear: "You've reached your Cloud voice quota"
   - User confirms this is the right UX
   - Test "Continue with Local" → should switch to browser TTS, playback resumes
   - Test "Upgrade Plan" → should navigate to /subscription

6. **User confirms both states look/work correctly before marking done.**

## Handoff

Ready for implementation. Key decisions are made:

- **Modal on quota exceeded** with two CTAs (Continue Local / Upgrade)
- **Progress bar warning** at 95%+ (brownish/amber color)
- **Detection**: check if `connectionError?.includes("Usage limit exceeded")`

Start by:
1. Finding where the Plan button progress bar is rendered (likely in sidebar or a shared component)
2. Adding color logic based on usage percentage from subscription context
3. Adding modal component (AlertDialog from shadcn) to SoundControl or PlaybackPage
4. Testing interactively with user via database manipulation — user must confirm each state before proceeding
