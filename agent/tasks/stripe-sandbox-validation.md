---
status: done
type: validation
depends-on: stripe-iac-portal, stripe-promo-codes
---

# Stripe Sandbox Validation

Parent: [[stripe-integration]]

## Goal

Validate the entire Stripe integration by setting up a **fresh sandbox** using only IaC scripts. This proves our setup is reproducible and documented.

## Prerequisites

- [ ] [[stripe-iac-portal]] complete — portal config via API
- [ ] [[stripe-promo-codes]] complete — promo codes in stripe_setup.py
- [ ] All IaC in stripe_setup.py tested individually

## Validation Steps

### 1. Create Fresh Stripe Test Environment

```bash
# Use a new Stripe test mode or clear existing test data
# Document exact steps
```

### 2. Run IaC Script

```bash
source .env && python scripts/stripe_setup.py --test
```

**Expected output:**
- Products created (Basic, Plus, Max)
- Monthly + Yearly prices for each
- Promo codes (BETA, LAUNCH, LAUNCHPLUS)
- Portal configuration applied

### 3. Verify in Dashboard

- [ ] Products exist with correct prices
- [ ] Portal config shows correct settings
- [ ] Promo codes exist and are active

### 4. Test IaC Updates (Idempotency)

Verify the upsert pattern works:

```bash
# Run script again — should be idempotent
python scripts/stripe_setup.py --test
```

- [ ] No errors on re-run
- [ ] No duplicate products/prices created

Then test actual updates:
- [ ] Change a promo code's `active` status in script → verify it updates in Stripe
- [ ] Change portal config setting → verify it updates
- [ ] Change something immutable (e.g., price amount) → verify appropriate warning/handling

### 5. Run E2E Tests

Use [[stripe-e2e-testing]] workflow to verify:
- [ ] New subscription flow
- [ ] Upgrade/downgrade
- [ ] Promo code application
- [ ] Cancel/reactivate

### 6. Document Any Manual Steps

If anything required Dashboard intervention, document it in [[stripe-integration]] Dashboard Manual Checklist.

## Results

*(To be filled during validation)*
