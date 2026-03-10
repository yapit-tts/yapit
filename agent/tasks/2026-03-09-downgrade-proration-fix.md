# Fix Downgrade Proration: Schedule at Period End + Remove Grace Period

status: active

## Problem

When a user downgrades (e.g., Max -> Plus mid-cycle), two things happen:
1. Stripe immediately credits unused higher-tier time (~€20 refund)
2. Our app grants a grace period keeping higher-tier access until period end

The user gets premium features for free AND a credit. Max exploit per cycle: ~€20.

## What Changed

As of Feb 9, 2026, Stripe Managed Payments now supports subscription schedules. This was the blocker that forced us to build the grace period workaround (`_clear_portal_schedule_conditions()` in stripe_setup.py).

## Goal

- Portal downgrades deferred to period end (Stripe-native, no proration, no credit)
- Portal upgrades unchanged (immediate, `always_invoice`)
- Remove grace period fields (`grace_tier`, `grace_until`) and `previous_plan_id` from UserSubscription (two-phase: code stops using them now, column drop later)
- Add `plan_id` to UsagePeriod so rollover is self-contained
- Enable Adaptive Pricing on checkout

## Done When

- [x] `stripe_setup.py` enables `schedule_at_period_end` with both conditions
- [x] Code no longer reads/writes grace_tier, grace_until, previous_plan_id
- [x] UsagePeriod has `plan_id` + migration + backfill
- [x] Rollover uses UsagePeriod.plan_id instead of grace_tier
- [x] Mid-cycle upgrade updates UsagePeriod.plan_id
- [x] Adaptive pricing enabled on checkout sessions
- [x] Unit tests updated and passing (353 pass)
- [ ] Manual test in Stripe test mode: `stripe_setup.py --test` applies config
- [ ] Manual test in Stripe test mode: downgrade shows "changes at period end"
- [ ] Manual test in Stripe test mode: upgrade still immediate
- [ ] Deployed to prod, tested with own account
- [ ] Knowledge files updated (stripe-integration.md)
- [ ] Phase 2 migration: drop grace_tier, grace_until, previous_plan_id columns (after all active grace periods expire)

## Plan

agent/research/2026-03-09-downgrade-proration-fix-plan.md
