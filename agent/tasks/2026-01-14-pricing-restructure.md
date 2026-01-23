---
status: done
started: 2026-01-14
completed: 2026-01-23
---

# Task: Pricing & Limits Restructure

## Intent

Restructure subscription pricing and usage limits to ensure profitability. Switch from page-based to token-based billing to eliminate exploit vectors and make costs fully predictable.

## Final Pricing (2026-01-21 — LOCKED IN)

**Token-based billing** — eliminates page exploit (adversarial PDFs can't game flat per-page pricing).

| Plan | Monthly | Yearly (25% off) | Tokens | ~Pages | Voice | ~Hours | Break-even (HU) |
|------|---------|------------------|--------|--------|-------|--------|-----------------|
| Basic | €10 | €90 | 5M | ~588 | — | — | 303% / 236% ✅ |
| Plus | €20 | €180 | 10M | ~1176 | **1M** | ~20h | 155% / 118% ✅ |
| Max | €40 | €360 | 15M | ~1764 | 3M | ~60h | 139% / 105% ✅ |

**Changes from earlier draft:**
- Plus voice: 1.2M → 1M (cleaner number, improves Plus Yearly break-even from 108% → 118%)
- Hours calculated at ~14 chars/second average (measured across voices, see [[inworld-tts]]). TTS-1-Max uses 2x chars, so halve for effective hours.

**Trial days:** 3 days Basic, 3 days Plus, 0 days Max

**Stripe tax_behavior:** `unspecified` — inherits from account-level Tax Settings ("automatic" = inferred_by_currency: EUR inclusive, USD/CAD exclusive)

**Token equivalents:** `input_tokens + (output_tokens × 6)` — output costs 6× input.

**Why these margins are trustworthy:** With token-based billing, cost = tokens × rate. No estimation uncertainty. The 105% break-even is *actually* 105%, not "assuming our page estimates hold."

**UI messaging:** Show "~500 / ~1000 / ~1500 pages" with hint that actual pages vary by content complexity (math/tables use more tokens → fewer pages; simple text → more pages).

## Token-Based Billing Model

**Cost calculation:**
- Input: $0.50/M tokens
- Output: $3.00/M tokens (6× input)
- Token equiv = input + (output × 6)
- Cost per token equiv = $0.50/M (input rate)

**Measured (N=208 pages):**
- Input: 2005 tokens/page (std ±226)
- Output: 890 tokens/page (std ±702 for complex content)

**Conservative estimates used:**
- Input: 2500 tokens (buffer for growing prompt)
- Output: 1000 tokens (buffer for complex pages)
- ~8500 token equiv/page → 5M ≈ 588 pages

## Rollover & Purchased Model

**Four fields on UserSubscription:**

```python
rollover_tokens: int = 0         # capped at 10M, can go NEGATIVE (debt)
rollover_voice_chars: int = 0    # capped at 1M, can go NEGATIVE (debt)
purchased_tokens: int = 0        # uncapped, from packs, NEVER negative
purchased_voice_chars: int = 0   # uncapped, from packs, NEVER negative
```

**Consumption waterfall:**
1. Subscription limit (counter goes UP, resets each billing cycle)
2. Rollover IF positive (skip if negative/debt)
3. Purchased (pure pool, down to 0)
4. **Overflow → rollover debt** (rollover goes more negative)

**Negative balance = debt in rollover:**
- Rollover can go negative to represent debt
- Purchased is "pure" — never touched by debt, user explicitly paid for it
- Debt is visible in `check_usage_limit`: `total_available = subscription + rollover + purchased`
- If net-negative, user blocked from new operations until topped up

**On billing cycle reset:**
```python
# Unused subscription tokens first pay off debt, then accumulate
unused = max(0, plan_limit - period_used)
# Addition naturally handles debt: -50K + 30K = -20K
new_rollover = min(rollover_tokens + unused, MAX_ROLLOVER_TOKENS)
```

**On purchased credits (when packs implemented):**
```python
# Purchased credits MUST clear debt first before adding to pool
# See "Future: Credit Pack Backend" section for implementation details
if rollover_tokens < 0:
    debt_payment = min(purchased_amount, -rollover_tokens)
    rollover_tokens += debt_payment
    purchased_amount -= debt_payment
purchased_tokens += purchased_amount
```

**Key behaviors:**
- Rollover/purchased persist after cancellation (they paid for it)
- Free tier users can buy packs
- Packs: Stripe/frontend deferred until demand confirmed; backend infrastructure now

## Bug Fix: Usage Check Before Cache

**Yoinked from [[2026-01-17-onboarding-showcase-launch]]**

Current `ws.py:273-335` checks usage on ALL blocks before checking cache. Fix: check cache first, only count uncached blocks. Required for 3-tier waterfall.

## Document Billing: Exploit Protection & Pre-Check

**The problem:** We don't know actual token cost until AFTER Gemini processes. Malicious PDFs could have millions of tokens per page (dense text), costing us hundreds of dollars while user pays nothing.

**Solution: PyMuPDF pre-check with tolerance buffer**

Before sending anything to Gemini, extract text locally with PyMuPDF to estimate tokens:

```python
# extraction.py: estimate_document_tokens()
for page in pages:
    if is_scanned_page(page):  # raster/image
        estimate = 10_000 tokens  # conservative fixed (accounts for 6x output cost)
    else:  # text-based
        text = pymupdf.extract_text(page)
        input_tokens = len(text) // 4  # ~4 chars per token
        output_tokens = input_tokens // 2  # ~50% of input (measured: 45%)
        estimate = input_tokens + (output_tokens × 6)  # token equiv
```

**Tolerance buffer favors user:**
```python
tolerance = 2_000 × num_pages  # per-page buffer
amount_to_check = max(0, estimated_tokens - tolerance)
# If estimate=55K, tolerance=10K (5 pages), we check if user has 45K (not 55K)
```

This means:
- User is leniently allowed to process documents where estimate slightly exceeds balance
- Actual might exceed estimate → balance goes negative (debt in rollover)
- Debt is small/bounded, not unbounded exploit

**Why this stops the exploit:**
- Text PDFs: actual estimate from extracted text catches million-token pages
- Raster PDFs: limited by image resolution (Gemini can't hallucinate text not in pixels)
- The 10K raster estimate + tolerance gives headroom for complex math/tables

**Atomic billing (TOCTOU safety):**
- `check_usage_limit` is a soft pre-filter (no lock) — catches obvious overages
- `record_usage` uses `SELECT ... FOR UPDATE` to atomically consume
- Concurrent requests serialize at billing time
- With pre-check protecting against big exploits, small TOCTOU races are bounded by rate limiting (max 5 concurrent document requests)

**Cancellation mechanism:**
- Redis flag `extraction:cancel:{content_hash}` checked before each page
- Pages pending (not yet sent to Gemini) are skipped
- In-flight pages complete (can't cancel mid-Gemini-request)
- User billed only for completed pages

**Metrics for tuning estimates:**
Actual tokens already logged via `page_extraction_complete`. Need to also log `estimated_tokens` (from pre-check) so we can compare estimate vs actual. This data allows tuning the tolerance:
- Lower tolerance → fewer negative balances, but more false rejections (user has enough but gets blocked)
- Higher tolerance → fewer rejections, but more potential debt
- Need production data to find the right balance

**Frontend UX for pre-check failure:**
When estimated cost exceeds balance, **don't partially process**. Instead, upfront rejection with options:
- "This document's estimated cost (~X tokens) exceeds your available balance (Y tokens)"
- Options: "Select fewer pages" / "Top up balance" / "Upgrade plan"
- This is distinct from user-initiated cancellation mid-processing

## Implementation Order

1. **DB/backend changes:**
   - Token-based billing (replace page fields with token fields)
   - Rollover + purchased fields on UserSubscription
   - 3-tier consumption waterfall
   - Bug fix: cache check before usage limit

2. **Stripe SDK upgrade (12→14) + billing code cleanup:**
   - Update `pyproject.toml`: `stripe~=12.0` → `stripe~=14.2`
   - Fix imports: `from stripe.<MODULE> import X` → `from stripe import X`
   - Make access patterns consistent (object access, not mixed dict/object)
   - Use typed params where practical
   - (Can do during step 1 alongside token billing changes)

**⚠️ CRITICAL: Verify Gemini token usage extraction**
- Confirm Gemini API reliably returns `usage.input_tokens` and `usage.output_tokens`
- Double-check our extraction code is correct
- This makes or breaks the business model — incorrect token counting = bankruptcy

3. **Stripe products + frontend:**
   - New products/prices in Stripe
   - Update seed.py + prod DB
   - Frontend pricing page updates

## Sources

**Tools:**
- `scripts/margin_calculator.py` — token-based margin analysis

**Related tasks:**
- [[2026-01-17-onboarding-showcase-launch]] — bug fix yoinked from here

**References:**
- Stripe MoR changelog: https://docs.stripe.com/payments/managed-payments/changelog
- Gemini 3 Flash pricing: https://ai.google.dev/gemini-api/docs/pricing

---

## Production Migration Notes

**After deploying the token billing migration (`df88ca3f6320`):**

The migration adds `ocr_tokens` column but leaves it NULL. Must run manually:

```sql
-- Update plan token limits (REQUIRED or plans have NULL limits!)
UPDATE plan SET ocr_tokens = 0 WHERE tier = 'free';
UPDATE plan SET ocr_tokens = 5000000 WHERE tier = 'basic';
UPDATE plan SET ocr_tokens = 10000000 WHERE tier = 'plus';
UPDATE plan SET ocr_tokens = 15000000 WHERE tier = 'max';
```

**After Phase 3 (Stripe price changes):**

Update prod DB plan prices to match new Stripe prices. Cannot re-run seed.py (unique constraint on tier) - use SQL UPDATE.

**Note:** seed.py currently has outdated prices (€7/€75 Basic). Update to match task file (€10/€90) in Phase 3.

---

## Done When

### Phase 1: Backend Token Billing
- [x] Token-based billing implemented (replaces page-based)
- [x] Rollover + purchased token/voice fields on UserSubscription
- [x] Usage checking/consumption uses 3-tier waterfall
- [x] Bug fix: cache check before usage limit (per-block checking)
- [x] Margin calculator updated with token-based model
- [x] Gemini token extraction verified (parallel research agent)
- [x] All tests pass (fixed message format in test_tts_billing.py: `status="error"` not `type="error"`)
- [x] Code cleanup: skip `_queue_synthesis_job` for cached blocks (early return in `_handle_synthesize`)
- [x] Update outdated comments (UsageLog docstring: "token equivalents" / "character equivalents")
- [x] Fix BlockVariant schema: removed broken `block_id` FK (was incompatible with content-addressed caching)

### Phase 2: Stripe SDK + Cleanup
- [x] Stripe SDK upgraded to 14.x
- [x] Fix imports and access patterns

### Phase 3: Stripe Products + Frontend
- [x] New limits/prices in seed.py
- [x] Update `scripts/stripe_setup.py` with new products/prices (v2 lookup keys, new coupons YAP10/VIP)
- [x] Handle existing Stripe state — user confirmed "Done"
- [x] Update prod DB plan prices + Stripe price IDs (see migration notes above) — done 2026-01-23
- [x] Frontend pricing page updates (raw chars/tokens display, value comparison table, rollover messaging)
- [x] New Stripe sandbox, E2E tests pass — see [[stripe-testing-pricing-restructure]]
- [x] Utilize `uncached_pages` from prepare response in frontend (show cached pages as "free")
- [x] Display rollover/purchased balances in usage UI
- [~] ~~Cost preview~~ — intentionally skipped: estimates are inaccurate, users shouldn't have to think about limits 90% of the time, usage shown after consumption is sufficient

### Phase 1.5: Document Billing Cleanup (2026-01-20)
- [x] Fix gemini.py PageResult refactor (tuple/dataclass mismatch, method rename, missing fields)
- [x] Complete cancellation: add cancel endpoint (`POST /v1/documents/extraction/cancel`)
- [x] Clarity refactor billing.py rollover code (comments/logging for debt payoff at cycle reset)
- [x] Add metrics logging for estimated tokens (`extraction_estimate` event with text_chars, raster/text page breakdown)
- [x] Tests for document billing edge cases (debt accumulation, debt blocking, waterfall skip)
- [x] Fix test_gemini_processor.py tests (updated for `_call_gemini_for_page` rename)
- [x] Refactor document processors: separate extraction from billing orchestration
  - `BaseDocumentProcessor` → `ProcessorConfig` + `process_with_billing()` in `processing.py`
  - `GeminiProcessor` → `GeminiExtractor` (async iterator yielding `PageResult`)
  - `MarkitdownProcessor` → `markitdown.extract()` function
  - Per-page billing/caching in service layer (was batch at end)
  - Markitdown now cached too (`markitdown:v1` prefix)
  - New `test_processing.py` tests billing orchestration with fake extractors

### E2E Verification (after code complete)
- [ ] Test blank/black/unreadable pages with Gemini (how does it respond? empty text? error?)
- [ ] Manual test of document processing flow to verify refactored code works
- [x] ~~Test with US billing address~~ — N/A: EUR-only pricing means VAT is always inclusive. USD tax behavior irrelevant until we add USD prices.

### Bugs Found
- [x] **Cancellation resets usage limits** — Fixed. Tested in [[stripe-testing-pricing-restructure]] Part 4.2: limits unchanged after cancel. Also fixed `cancel_at` handling for trial subscriptions (commit `003d01f`).

### E2E Testing Protocol v2
Completed in [[stripe-testing-pricing-restructure]]:
- [x] Model around user flows: subscribe → use → cancel within trial, cancel after trial, upgrade, downgrade
- [x] Cancel from portal → limits NOT reset until period end
- [x] Grace period behavior on downgrades (3.3-3.6)
- [x] Rollover calculation at billing cycle reset (1.1, 1.4)
- [x] Debt accumulation and blocking (1.3, 1.4)

### Deferred
- [ ] Stripe products for token/voice packs
- [ ] Frontend for purchasing packs

---

## Future: Credit Pack Backend

**When implementing credit pack purchases, the Stripe webhook handler MUST:**

1. **Clear rollover debt first before adding to purchased pool**

```python
# In Stripe webhook for pack purchase
async def handle_pack_purchase(user_id: str, token_amount: int, db: AsyncSession):
    subscription = await get_user_subscription(user_id, db, for_update=True)

    # Pay off rollover debt first
    if subscription.rollover_tokens < 0:
        debt_payment = min(token_amount, -subscription.rollover_tokens)
        subscription.rollover_tokens += debt_payment
        token_amount -= debt_payment
        logger.info(f"Pack purchase: {debt_payment} tokens paid off rollover debt")

    # Remainder goes to purchased pool
    subscription.purchased_tokens += token_amount
    logger.info(f"Pack purchase: {token_amount} tokens added to purchased pool")
```

2. **Why this matters:**
   - Without this, user could accumulate infinite debt, buy small packs, and keep using the service
   - Debt must be cleared before purchased credits become usable
   - The `check_usage_limit` already counts negative rollover against total_available, so without clearing debt, purchased credits would just offset the debt in the check but not actually pay it off

3. **Location:** `yapit/gateway/api/v1/billing.py` — add new webhook handler for pack purchase events

---

## Observability TODOs

- [x] Log estimated tokens in pre-check — `extraction_estimate` event already exists; added `content_hash` to `page_extraction_complete` for correlation (7aca6ea)
- [x] Update monitoring agent prompt (`scripts/report.sh`) — added new event types (stripe_webhook, url_fetch, playwright_fetch) (7aca6ea)
- [x] Help docs explainer for billing model — TODO added to TipsPage.tsx
