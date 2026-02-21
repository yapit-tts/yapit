---
status: done
refs:
  - "[[2026-02-21-red-team-security-audit]]"
---

# Remove `synthesis_mode` billing bypass

## Intent

`synthesis_mode="browser"` skips the billing check in `synthesis.py:107-113` but the server still queues and processes the TTS job. Any client (including anonymous) can get unlimited server-side synthesis by setting this field to `"browser"`.

The field is dead code — the frontend never sends `synthesis_mode="browser"` to the server. Browser TTS runs entirely client-side via `browserSynthesizer.ts` (Kokoro.js Web Worker). The server synthesizer always hardcodes `synthesis_mode: "server"` (`serverSynthesizer.ts:89`).

This is a remnant of the old architecture where browser workers sent audio back to the gateway.

## Done When

- `synthesis_mode` parameter removed from `request_synthesis()` and `WSSynthesizeRequest`
- Billing check runs unconditionally
- Tests updated
