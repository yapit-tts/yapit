---
status: active
started: 2026-01-14
---

# Task: Pricing & Limits Restructure

## Intent

Restructure subscription pricing, usage limits, and add rollover/add-on features to ensure profitability across all plans in worst-case scenarios (Hungary 27% VAT, 100% utilization, conservative cost estimates).

Current limits were set before accurate cost analysis. With real Gemini 3 Flash pricing ($0.50/M in, $3.00/M out) and Stripe MoR fees (7% + €0.30), several plans lose money at full utilization.

## Constraints

**Hard constraints:**
- All plans must have ≥0% margin at 100% utilization + Hungary VAT (worst case)
- Voice limits stay as-is: 1.2M chars (Plus), 3M chars (Max)
- Basic/Plus yearly discounts (11%, 20%) are acceptable
- Max Yearly 50% discount is NOT acceptable — must be reduced

**Cost basis (conservative estimates):**
- Gemini 3 Flash: $0.50/M input, $3.00/M output
- High resolution: 1120 tokens/image + ~1500-2000 prompt tokens
- Output: ~1500-2000 tokens/page (conservative; real avg ~500-1000)
- Result: ~€5.61/1000 pages
- Inworld TTS-1: $5.00/M chars = €4.63/M chars
- Stripe MoR: 7% + €0.30 (conservative for international cards)
- VAT range: 0% (some US states) to 27% (Hungary)

## Current State (Problematic)

| Plan | Price | OCR/mo | Voice/mo | Break-even (Hungary) |
|------|-------|--------|----------|---------------------|
| Basic Monthly | €7 | 500 | 0 | 172% ✅ |
| Basic Yearly | €75 | 500 | 0 | 162% ✅ |
| Plus Monthly | €20 | 1500 | 1.2M | 103% ⚠️ |
| Plus Yearly | €192 | 1500 | 1.2M | 84% ❌ |
| Max Monthly | €40 | 3000 | 3.0M | 94% ❌ |
| Max Yearly | €240 | 3000 | 3.0M | 48% ❌❌ |

## Direction

### 1. Adjust Base Pricing

- Basic: €7 → €10 (gives more OCR headroom)
- Plus/Max monthly: likely keep prices, reduce OCR limits
- Max Yearly: reduce discount from 50% to ~30-40%

### 2. Reduce OCR Limits

Calculate limits that give ≥100% break-even at Hungary VAT. Preliminary safe ranges:
- Basic €10: up to ~1000 pages safe
- Plus €20: ~700-900 pages safe (after voice costs)
- Max €40: ~1500-2000 pages safe (after voice costs)
- Max Yearly: severely constrained by voice costs eating budget

### 3. Add Rollover System

**Fixed universal cap (not plan-based, not time-limited):**
- Pages: ~1500 cap
- Voice chars: ~1M cap
- Never expires (even after cancellation — they paid for it)
- Only consumed after monthly subscription limit exhausted

Implementation: add `rollover_pages` and `rollover_voice_chars` to user model, capped at fixed values.

### 4. Add Page Packs (One-Time Purchases)

Stripe MoR now supports one-time payments (as of Sept 2025).

**Preliminary pricing (15-25% nominal margin, ~40-50% real margin):**
- 100 pages: ~€1.50
- 250 pages: ~€3.00
- 500 pages: ~€5.50
- 1000 pages: ~€10.00

Note: €0.30 Stripe fixed fee hurts small packs. Consider minimum pack size of 250.

**Implementation:** Store purchased pages separately, never expire, consumed after subscription + rollover exhausted.

**Defer until:** Beta tester usage data confirms actual cost-per-page.

## Open Questions

1. **Exact OCR limits per tier** — run margin calculator with candidate values, verify ≥100% break-even
2. **Max Yearly price** — what discount is acceptable? €290 (40%)? €320 (33%)?
3. **Rollover cap values** — 1500 pages / 1M chars confirmed, or adjust?
4. **Add-on pack sizes and prices** — wait for real usage data before finalizing
5. **Voice packs** — needed? Or just page packs for now?

## Sources

**Tools:**
- `scripts/margin_calculator.py` — comprehensive margin analysis with all cost components

**References:**
- Stripe MoR changelog (Sept 22, 2025 - one-time payments added): https://docs.stripe.com/payments/managed-payments/changelog
- Stripe MoR setup guide: https://docs.stripe.com/payments/managed-payments/set-up
- Stripe MoR update checkout integration: https://docs.stripe.com/payments/managed-payments/update-checkout
- Gemini 3 Flash pricing: https://ai.google.dev/gemini-api/docs/pricing
- Inworld TTS pricing: https://inworld.ai/pricing

## Done When

- [ ] All plans have ≥100% break-even at Hungary VAT + 100% utilization
- [ ] New limits/prices reflected in seed.py and frontend
- [ ] Rollover system implemented (fixed cap, never expires)
- [ ] Add-on page packs available for purchase (can be post-launch)
- [ ] Margin calculator updated with final values, confirms profitability
