---
status: done
started: 2026-01-03
completed: 2026-01-23
---

# Task: Rate Limiting, Fair Use & Document Storage Limits

## Intent

Protect system resources from overload while maintaining generous limits for normal users.

## Implementation

See commit `506b974` for full changes.

---

## Key Decisions & Rationale

### Skipped: TTS Pending Job Limit (500)

Original plan called for limiting pending TTS jobs via Redis counter on `TTS_PENDING`. We skipped this because:

1. **Wrong abstraction level** — `TTS_PENDING` tracks per-user-per-document sets. Counting total requires either SCAN+SCARD (expensive) or maintaining a separate counter (sync complexity across 3 code paths: add, evict, complete).

2. **Rate limiting achieves the same goal** — The concern was Kokoro flooding from "unlimited" users. A simple 300/min rate limit on synthesize messages bounds sustained abuse without Redis state complexity.

3. **Request-level is cleaner** — "Users can't spam requests" is an HTTP/WebSocket concern, not a Redis data structure concern.

### TTS Rate Limit: 300/min

**Napkin math:**
- Normal reading: ~1 block every 5-10 seconds = 6-12 requests/min
- Prefetch window: 8 blocks ahead = burst of 8 on skip
- Rapid skipping: could hit 30-50 requests in seconds
- 300/min = 5/sec sustained, generous but caps abuse

**Fixed window boundary issue:** User could do 300 at t=58-60, then 300 more at t=60-62 = 600 in ~4 seconds. Accepted because:
- Still bounded (can't sustain >300/min average)
- Must wait ~58 seconds before next burst
- Goal is preventing sustained flooding, not every possible burst

### Concurrent Extractions: 3

Bounds TOCTOU race exposure in billing. With pre-check, multiple concurrent requests could all pass before any billing happens. 3 is generous (nobody legitimately needs more) and caps potential debt from races.

### `ever_paid` vs `highest_tier_subscribed`

`highest_tier_subscribed` includes trials (user entered card but didn't pay). We wanted strict "contributed revenue" for document limits. Added `ever_paid: bool` field set on:
- `invoice.payment_succeeded` webhook (primary)
- `checkout.completed` when status=active (fallback for non-trial, handles webhook race)

**Webhook race consideration:** If invoice webhook arrives before checkout webhook, we log error but checkout.completed still sets `ever_paid` correctly for non-trial subs.

### ToS: Rollover & Negative Balance

Added soft rollover mention: "Unused allowances may roll over to subsequent periods, subject to caps."

**Legal assessment on negative rollover:** Low risk because:
- Net fairness: user got more in period A, less in period B, evens out
- User benefit: alternative (hard cutoff) is worse UX
- Standard practice: mobile carriers, cloud services all do this
- Covered by "subject to caps" + "fair use" language

---

## Deferred

- **Monitoring agent prompt** (`scripts/report.sh`) — Can add later when we observe patterns worth flagging
- **Dashboard charts** — Nice-to-have, not blocking

---

## Assumptions

- Billing pre-check (PyMuPDF estimate) handles most TOCTOU risk; rate limits are defense-in-depth
- 300/min TTS is generous enough for any legitimate use including rapid navigation and future MP3 export (which would chunk requests)
- Document limits (50/100/1000) are conservative starting points; easier to increase than decrease
