---
status: done
---

# Metrics & Logging Audit

## Intent

Audit whether our metrics and logging are sufficient to answer every operational question that matters: diagnosing failures, understanding performance, ensuring billing accuracy, and detecting capacity issues — before users report them.

## Assumptions

- We care about service reliability, not engagement. Users upload docs, listen to what they want.
- Extraction quality is unmeasurable without user feedback (out of scope).
- Browser-side Kokoro.js failures are mostly out of our control (low priority).
- 80% focus on backend observability.

## Questions the Observability Stack Must Answer

### User Experience
- What is time-to-first-audio (user presses play → first audio byte over WebSocket)?
- Is there buffer underflow? (user wants to listen but audio isn't ready yet)

### Pipeline Health & Reliability
- Which worker/model is degraded right now?
- What's the retry rate, and why?
- Are we hitting rate limits on external APIs (Gemini, Inworld)?
- How long do jobs sit in queue before pickup?

### Performance & Capacity
- At what usage level do we saturate?
- Cost per document / per character?
- How does latency change under load?
- Over/under-provisioned?

### Error Diagnosis
- Can we trace a single user request end-to-end?
- When synthesis fails, can we reconstruct exactly why?
- When extraction fails, can we see input + Gemini response?

### Billing
- Is usage tracking accurate (characters counted = characters synthesized)?
- Double charges, missed charges — detectable?

### Security / Abuse
- Unusual usage spikes per user?
- Auth failures?

## Research

- [[metrics-logging-audit-findings]] — deep code review of what's actually instrumented vs. what should be

## Done When

- Concrete list of observability gaps with severity
- Actionable recommendations for each gap
