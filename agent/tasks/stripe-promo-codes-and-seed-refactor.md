---
status: active
type: implementation
---

# Task: Stripe Promo Codes & Seed Refactor

Related: [[pricing-strategy-rethink]], [[subscription-backend-refactor]], [[stripe-iac-improvements]]

## Goal

1. Rename `dev_seed.py` → `seed.py` (it's used in prod, naming is misleading)
2. Move Stripe price IDs from hardcoded in seed to environment config
3. Add promo code support to checkout and `stripe_setup.py`
4. Configure trial periods per plan

## Constraints / Design Decisions

**Seed naming:** `seed.py` (not `dev_seed.py`) — it runs in all environments.

**Price IDs in env, not sops:** Price IDs are public (visible in checkout HTML). Put in `.env.dev` (test) and `.env.prod` (live), not encrypted.

**Promo codes enabled at checkout:** Users enter codes in Stripe's checkout form (appears automatically when `allow_promotion_codes=True`).

**Trial + promo can stack:** Trial delays first charge, promo discounts the charge. They work together.

## Next Steps

1. Rename `dev_seed.py` → `seed.py`, update import in `db.py:74`
2. Add Stripe price ID fields to `Settings` (config.py)
3. Create `.env.prod` file for live Stripe price IDs
4. Update seed to read price IDs from settings instead of hardcoded
5. Update trial_days in seed: Basic=3, Plus=3, Max=0
6. Add `allow_promotion_codes: True` to checkout params in `billing.py`
7. Add coupon/promo code creation to `stripe_setup.py`
8. Run `stripe_setup.py --test` to create test coupons
9. Test checkout with promo code

## Open Questions

### Stripe Price Update Workflow (needs clarification)

**Context:** Stripe prices are IMMUTABLE — once created, you cannot change the amount.

**Questions to resolve:**

1. **What is `lookup_key`?**
   - It's a stable identifier YOU define (e.g., `yapit_basic_monthly`)
   - Lets you find prices by your key instead of Stripe's `price_xxx` ID
   - Different from product ID

2. **How does idempotency work?**
   - Script creates price with `lookup_key: "yapit_basic_monthly"`
   - If price exists with that lookup_key → returns existing ID
   - If you change amount in script (€7 → €8) → ERROR (can't create duplicate lookup_key with different amount)

3. **Workflow for changing prices:**
   - Option A: Use `transfer_lookup_key: true` when creating new price
     - Creates new price (€8) and transfers lookup_key from old price (€7)
     - Old price auto-archived
   - Option B: Archive old price manually, create new with new lookup_key
   - **Need to verify:** Does transfer_lookup_key work smoothly? What happens to existing subscriptions?

4. **What needs to change in backend when prices change?**
   - Run `stripe_setup.py` with updated amounts
   - Get new price IDs
   - Update `.env.dev` / `.env.prod` with new IDs
   - Re-seed DB (or migration to update Plan.stripe_price_id_*)
   - **Existing subscriptions:** Stay on old price until renewal (Stripe handles this)

5. **Can we have two €7 prices?**
   - Yes, but they'd need different lookup_keys
   - Each price is unique (price_xxx ID), lookup_key is just your alias

**TODO:** Test price update workflow before launch. Document in knowledge file once verified.

## Notes / Findings

### Stripe Promo Code Architecture

**Sources:**
- [Coupons and promotion codes overview](https://docs.stripe.com/billing/subscriptions/coupons)
- [Coupons API reference](https://docs.stripe.com/api/coupons)
- [Promotion Codes API reference](https://docs.stripe.com/api/promotion_codes)
- [Create a promotion code](https://docs.stripe.com/api/promotion_codes/create)
- [Update a promotion code](https://docs.stripe.com/api/promotion_codes/update) — confirms `max_redemptions` not editable
- [Trial periods on subscriptions](https://docs.stripe.com/billing/subscriptions/trials)
- [Add discounts to Checkout](https://docs.stripe.com/payments/checkout/discounts)

**Coupons vs Promotion Codes:**
- **Coupon**: The discount definition (e.g., "30% off for 3 months")
- **Promotion Code**: Customer-facing code that maps to a coupon (e.g., "LAUNCH" → 30% off coupon)
- One coupon can have multiple promo codes
- Promo codes can have: max_redemptions, expiration date, first-time-only restriction

**Key limitations:**
- `max_redemptions` CANNOT be increased after creation — create new code if need more
- `active` CAN be toggled (to disable/re-enable a code)
- Coupon details (amount, duration) CANNOT be changed after creation

**Creating via API (for stripe_setup.py):**
```python
# Create coupon
coupon = client.v1.coupons.create({
    "id": "launch_basic_100",  # Our internal ID
    "percent_off": 100,
    "duration": "once",  # or "repeating" with duration_in_months
    "duration_in_months": 1,  # only if duration="repeating"
    "name": "Launch - Free Basic Month",
})

# Create promo code pointing to coupon
promo = client.v1.promotion_codes.create({
    "coupon": "launch_basic_100",
    "code": "LAUNCH",
    "max_redemptions": 300,
    # Optional: "expires_at": unix_timestamp,
    # Optional: "restrictions": {"first_time_transaction": True}
})
```

**Idempotency:** Use try/except pattern like existing product/price creation:
- Try create → catch "already exists" → look up existing

**Enabling in checkout:**
```python
# billing.py checkout_params
checkout_params["allow_promotion_codes"] = True
```

This adds a "Add promotion code" link to Stripe's checkout form automatically.

### Price IDs Environment Strategy

**Current problem:** `dev_seed.py` has test price IDs hardcoded, but it runs in prod too.

**Solution:** Read from Settings:
```python
# config.py
stripe_price_basic_monthly: str | None = None
stripe_price_basic_yearly: str | None = None
# ... etc for plus, max

# seed.py
Plan(
    tier=PlanTier.basic,
    stripe_price_id_monthly=settings.stripe_price_basic_monthly,
    stripe_price_id_yearly=settings.stripe_price_basic_yearly,
    ...
)
```

**Env files:**
- `.env.dev` — test Stripe price IDs (plain text, committed)
- `.env.prod` — live Stripe price IDs (plain text, on server only)
- `.env.sops` — only actual secrets (API keys, webhook secrets)

### Seed Update Behavior

Seed runs once on fresh DB. To change trial_days or other Plan fields post-launch:
- Create an alembic migration: `UPDATE plan SET trial_days = X WHERE tier = 'basic'`
- Or manual SQL

Not a code change to seed — seed only affects fresh DBs.

### Promo Code Configuration (Decided)

| Coupon ID | Discount | Duration | Code | Max Redemptions | Purpose |
|-----------|----------|----------|------|-----------------|---------|
| `beta_100` | 100% | 1 month | `BETA` | 10 | Private beta testers |
| `launch_basic_100` | 100% | 1 month | `LAUNCH` | 300 | Launch marketing (Basic) |
| `launch_plus_30` | 30% | 3 months | `LAUNCHPLUS` | 100 | Launch marketing (Plus) |

**BETA code:** Deactivate at launch (set `active=False` via API or dashboard).

**Budget exposure:**
- BETA: 10 × €7.50 max = €75
- LAUNCH: 300 × ~€0.50 (OCR only) = €150 max
- LAUNCHPLUS: 100 × positive margin (they pay €14/mo, costs you €7.50 max = €6.50+ profit)

### Trial Configuration (Decided)

| Tier | trial_days |
|------|------------|
| Basic | 3 |
| Plus | 3 |
| Max | 0 |

---

## Work Log

### 2025-12-31 - Seed Refactor Implemented

**Completed:**
1. `git mv dev_seed.py seed.py`
2. Updated `db.py` import: `from yapit.gateway.seed import seed_database`
3. Changed signature: `seed_database(db, settings)` — now takes settings for price IDs
4. Added price ID settings to `config.py`:
   - `stripe_price_basic_monthly`, `stripe_price_basic_yearly`
   - `stripe_price_plus_monthly`, `stripe_price_plus_yearly`
   - `stripe_price_max_monthly`, `stripe_price_max_yearly`
5. Added test price IDs to `.env.dev`
6. Added placeholder comments to `.env.prod` (need `stripe_setup.py --prod` output)
7. Updated `stripe_setup.py` output to show env var format
8. Renamed internal functions: `create_dev_*` → `create_*`

**Related task created:** [[admin-endpoints-and-soft-delete]] for soft delete and model management.

**Remaining in this task:** Promo code implementation (billing.py + stripe_setup.py).

### 2025-12-31 - Brainstorming Session

**Context:** User wanted to understand billing implementation status and how to give friends access during messy deploy state. Evolved into launch marketing strategy discussion.

**Key realizations during discussion:**
1. `dev_seed.py` is misnamed — it runs in prod via `DB_SEED=1`
2. Test Stripe price IDs are hardcoded in seed — won't work in prod
3. Price IDs aren't secret (visible in checkout) — don't need sops
4. Basic tier trials are nearly free (server Kokoro = €0 cost, only OCR risk)
5. Premium voice tiers (Plus/Max) are where real cost is

**User preferences established:**
- Free tier as main marketing (€0 cost to us)
- Invite-only beta with controlled promo codes
- Conservative trial lengths (3 days)
- Positive margins on all launch promos

**Stripe research conducted:**
- Promo code creation via API documented
- `max_redemptions` cannot be increased (must create new code)
- `active` can be toggled to disable codes
- `allow_promotion_codes: True` enables input field in checkout

**Files to modify:**
- `yapit/gateway/dev_seed.py` → rename to `seed.py`
- `yapit/gateway/db.py:74` → update import
- `yapit/gateway/config.py` → add price ID settings
- `yapit/gateway/api/v1/billing.py` → add `allow_promotion_codes`
- `scripts/stripe_setup.py` → add coupon/promo creation
- Create `.env.prod` for live price IDs
