---
status: active
started: 2026-01-14
---

# Task: Pricing & Limits Restructure

## Intent

Restructure subscription pricing, usage limits, and add rollover/add-on features to ensure profitability across all plans in worst-case scenarios (Hungary 27% VAT, 100% utilization, conservative cost estimates).

Current limits were set before accurate cost analysis. With real Gemini 3 Flash pricing ($0.50/M in, $3.00/M out) and Stripe MoR fees (7% + €0.30), several plans lose money at full utilization.

## Decided Pricing (2026-01-18)

All plans ≥100% break-even at Hungary 27% VAT. Uniform 20% yearly discount. OCR in 500-step progression.

| Plan | Price | OCR/mo | Voice/mo | Break-even (HU) |
|------|-------|--------|----------|-----------------|
| Basic Monthly | €10 | 500 | 0 | 250% ✅ |
| Basic Yearly | €96 | 500 | 0 | 208% ✅ |
| Plus Monthly | €20 | 1000 | 1.2M | 128% ✅ |
| Plus Yearly | €192 | 1000 | 1.2M | 105% ✅ |
| Max Monthly | €40 | 1500 | 3M | 130% ✅ |
| Max Yearly | €384 | 1500 | 3M | 105% ✅ |

**Changes from current:**
- Basic: €7 → €10/mo, yearly €75 → €96 (was 11% discount, now 20%)
- Plus: OCR 1500 → 1000 pages
- Max: OCR 3000 → 1500 pages, yearly €240 → €384 (was 50% discount, now 20%)

**Pending:** Verify actual token consumption per page before finalizing. Conservative estimate is €5.61/1000 pages, realistic might be €3.20/1000.

## Rollover & Purchased Model

**Two separate pools per resource type:**

```python
# On UserSubscription
rollover_pages: int = 0          # capped at 1000, from unused subscription
rollover_voice_chars: int = 0    # capped at 1_000_000
purchased_pages: int = 0         # uncapped, from packs
purchased_voice_chars: int = 0   # uncapped, from packs (future)
```

**Consumption order:**
1. Subscription limit (resets each billing cycle)
2. Rollover (capped, from unused subscription quota)
3. Purchased (uncapped, from pack purchases)

**On billing cycle reset:**
```python
unused = plan_limit - period_used
rollover_pages = min(rollover_pages + unused, 1000)
```

**On pack purchase:**
```python
purchased_pages += pack_pages  # no cap
```

**Key behaviors:**
- Rollover/purchased persist after cancellation (they paid for it)
- Free tier users can buy packs
- Packs: Stripe/frontend deferred until demand confirmed; backend infrastructure now

## Bug Fix: Usage Check Before Cache

**Yoinked from [[2026-01-17-onboarding-showcase-launch]]**

Current `ws.py:273-335` checks usage on ALL blocks before checking cache. User with 500 chars remaining fails on 2000-char request even if 1600 chars are cached.

**Fix:** Check cache first, only count uncached blocks for usage limit. This is required anyway for the 3-tier waterfall — need to know uncached amount before checking/decrementing pools.

## Constraints

**Cost basis (conservative estimates):**
- Gemini 3 Flash: $0.50/M input, $3.00/M output
- High resolution: 1120 tokens/image + ~2000 prompt tokens + ~1500 output tokens
- Result: ~€5.61/1000 pages (conservative), ~€3.20/1000 (realistic)
- Inworld TTS-1: $5.00/M chars = €4.63/M chars
- Stripe MoR: 7% + €0.30 (conservative for international cards)
- VAT: Stripe default (EUR inclusive, USD exclusive)

## Prerequisite: Stripe SDK Upgrade

Before pricing changes, upgrade Stripe SDK (12→14) and clean up billing code:

- Update `pyproject.toml`: `stripe~=12.0` → `stripe~=14.2`
- Fix imports: `from stripe.<MODULE> import X` → `from stripe import X`
- Make access patterns consistent (object access, not mixed dict/object)
- Use typed params where practical

Lower risk than pricing changes (just types/imports). E2E testing at the end catches issues from both.

## Sources

**Tools:**
- `scripts/margin_calculator.py` — margin analysis (updated with OCR%/Voice% columns)

**Related tasks:**
- [[2026-01-17-onboarding-showcase-launch]] — bug fix yoinked from here

**References:**
- Stripe MoR changelog: https://docs.stripe.com/payments/managed-payments/changelog
- Gemini 3 Flash pricing: https://ai.google.dev/gemini-api/docs/pricing
- Inworld TTS pricing: https://inworld.ai/pricing

---

## Done When

- [ ] Stripe SDK upgraded to 14.x, billing code cleaned up
- [ ] New limits/prices in seed.py, frontend, AND prod DB (already seeded)
- [ ] Rollover + purchased fields on UserSubscription, migration done
- [ ] Usage checking/consumption uses 3-tier waterfall (subscription → rollover → purchased)
- [ ] Bug fix: cache check before usage limit check
- [x] Margin calculator updated with final values (added OCR%/Voice% columns)
- [ ] New Stripe sandbox, E2E tests pass
- [ ] (Deferred) Stripe products for page/voice packs
- [ ] (Deferred) Frontend for purchasing packs
