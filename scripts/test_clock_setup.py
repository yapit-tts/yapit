#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["stripe>=13", "psycopg2-binary"]
# ///
"""Test clock setup helper for billing cycle tests.

Creates a Stripe test clock with customer, subscription, and matching DB records.
Useful for testing rollover, debt payoff, trial expiry, and grace period expiry.

Usage:
    uv run scripts/test_clock_setup.py --tier=plus --usage-tokens=2000000
    uv run scripts/test_clock_setup.py --tier=plus --advance-days=35  # Past first billing cycle
    uv run scripts/test_clock_setup.py --cleanup clock_xxx  # Delete a test clock

Environment:
    Requires STRIPE_SECRET_KEY and DATABASE_URL in .env
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2
import stripe


def load_env():
    """Load .env and .env.dev files."""
    script_dir = os.path.dirname(__file__)
    for env_file in [".env", ".env.dev"]:
        env_path = os.path.join(script_dir, "..", env_file)
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key, value)


def get_db_connection():
    """Get database connection. Uses localhost since script runs outside Docker."""
    # Build connection string for local access (not Docker internal)
    user = os.environ.get("POSTGRES_USER", "yapit")
    password = os.environ.get("POSTGRES_PASSWORD", "yapit")
    db = os.environ.get("POSTGRES_DB", "yapit")
    # Use localhost since we're running outside Docker
    return psycopg2.connect(f"postgresql://{user}:{password}@localhost:5432/{db}")


def get_price_id(tier: str, interval: str = "monthly") -> str:
    """Get Stripe price ID for a tier."""
    # These are the v2 lookup keys from stripe_setup.py
    lookup_keys = {
        ("basic", "monthly"): "yapit_basic_monthly_v2",
        ("basic", "yearly"): "yapit_basic_yearly_v2",
        ("plus", "monthly"): "yapit_plus_monthly_v2",
        ("plus", "yearly"): "yapit_plus_yearly_v2",
        ("max", "monthly"): "yapit_max_monthly_v2",
        ("max", "yearly"): "yapit_max_yearly_v2",
    }
    lookup_key = lookup_keys.get((tier, interval))
    if not lookup_key:
        raise ValueError(f"Unknown tier/interval: {tier}/{interval}")

    prices = stripe.Price.list(lookup_keys=[lookup_key], limit=1)
    if not prices.data:
        raise ValueError(f"Price not found for lookup key: {lookup_key}")
    return prices.data[0].id


def get_plan_id(tier: str, conn) -> int:
    """Get plan ID from database."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM plan WHERE tier = %s", (tier,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Plan not found for tier: {tier}")
        return row[0]


def create_test_clock(name: str = "Billing Test") -> dict:
    """Create a Stripe test clock frozen at current time."""
    clock = stripe.test_helpers.TestClock.create(
        frozen_time=int(time.time()),
        name=name,
    )
    print(f"Created test clock: {clock.id}")
    return clock


def create_customer(clock_id: str, email: str = "testclock@example.com") -> dict:
    """Create a customer attached to test clock."""
    customer = stripe.Customer.create(
        email=email,
        name="Test Clock User",
        test_clock=clock_id,
    )
    print(f"Created customer: {customer.id}")
    return customer


def create_subscription(customer_id: str, price_id: str, tier: str, trial_days: int = 3) -> dict:
    """Create subscription with trial and setup intent for payment."""
    sub = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        trial_period_days=trial_days,
        payment_behavior="default_incomplete",
        metadata={"user_id": f"testclock-{int(time.time())}", "plan_tier": tier},
    )
    print(f"Created subscription: {sub.id} (status: {sub.status})")

    # Confirm setup intent with test card if present
    if sub.pending_setup_intent:
        setup_intent_id = sub.pending_setup_intent
        if isinstance(setup_intent_id, str):
            # Create and attach a test payment method
            pm = stripe.PaymentMethod.create(
                type="card",
                card={"token": "tok_visa"},
            )
            stripe.PaymentMethod.attach(pm.id, customer=customer_id)

            # Confirm the setup intent
            stripe.SetupIntent.confirm(
                setup_intent_id,
                payment_method=pm.id,
            )

            # Set as default payment method
            stripe.Subscription.modify(
                sub.id,
                default_payment_method=pm.id,
            )
            print(f"Attached payment method: {pm.id}")

    return sub


def insert_db_records(
    conn,
    user_id: str,
    plan_id: int,
    tier: str,
    customer_id: str,
    subscription_id: str,
    period_start: int,
    period_end: int,
    usage_tokens: int = 0,
    usage_voice_chars: int = 0,
    rollover_tokens: int = 0,
    rollover_voice_chars: int = 0,
    status: str = "trialing",
):
    """Insert subscription and usage period records into DB."""
    with conn.cursor() as cur:
        # Insert/update subscription
        cur.execute(
            """
            INSERT INTO usersubscription (
                user_id, plan_id, status, stripe_customer_id, stripe_subscription_id,
                current_period_start, current_period_end, cancel_at_period_end,
                highest_tier_subscribed, rollover_tokens, rollover_voice_chars,
                purchased_tokens, purchased_voice_chars, created, updated
            ) VALUES (
                %s, %s, %s, %s, %s,
                to_timestamp(%s), to_timestamp(%s), false,
                %s, %s, %s, 0, 0, NOW(), NOW()
            ) ON CONFLICT (user_id) DO UPDATE SET
                plan_id = EXCLUDED.plan_id,
                status = EXCLUDED.status,
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                current_period_start = EXCLUDED.current_period_start,
                current_period_end = EXCLUDED.current_period_end,
                rollover_tokens = EXCLUDED.rollover_tokens,
                rollover_voice_chars = EXCLUDED.rollover_voice_chars,
                updated = NOW()
            """,
            (
                user_id,
                plan_id,
                status,
                customer_id,
                subscription_id,
                period_start,
                period_end,
                tier,
                rollover_tokens,
                rollover_voice_chars,
            ),
        )
        print(f"Inserted subscription for user: {user_id}")

        # Insert usage period if usage specified
        if usage_tokens > 0 or usage_voice_chars > 0:
            cur.execute(
                """
                INSERT INTO usageperiod (user_id, period_start, period_end, server_kokoro_characters, premium_voice_characters, ocr_tokens)
                VALUES (%s, to_timestamp(%s), to_timestamp(%s), 0, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (user_id, period_start, period_end, usage_voice_chars, usage_tokens),
            )
            print(f"Inserted usage period: {usage_tokens} tokens, {usage_voice_chars} voice chars")

        conn.commit()


def advance_clock(clock_id: str, days: int) -> dict:
    """Advance test clock by N days and wait for ready."""
    target_time = int(time.time()) + (days * 24 * 60 * 60)
    clock = stripe.test_helpers.TestClock.advance(clock_id, frozen_time=target_time)
    print(f"Advancing clock to {datetime.fromtimestamp(target_time, tz=timezone.utc)}")

    # Wait for clock to be ready
    for _ in range(30):
        clock = stripe.test_helpers.TestClock.retrieve(clock_id)
        if clock.status == "ready":
            print(f"Clock ready at {datetime.fromtimestamp(clock.frozen_time, tz=timezone.utc)}")
            return clock
        time.sleep(1)

    raise TimeoutError(f"Clock {clock_id} did not become ready")


def cleanup_clock(clock_id: str):
    """Delete a test clock."""
    stripe.test_helpers.TestClock.delete(clock_id)
    print(f"Deleted test clock: {clock_id}")


def main():
    parser = argparse.ArgumentParser(description="Set up Stripe test clock for billing tests")
    parser.add_argument("--tier", choices=["basic", "plus", "max"], default="plus", help="Subscription tier")
    parser.add_argument("--interval", choices=["monthly", "yearly"], default="monthly", help="Billing interval")
    parser.add_argument("--trial-days", type=int, default=3, help="Trial period days")
    parser.add_argument("--usage-tokens", type=int, default=0, help="OCR tokens to record as used")
    parser.add_argument("--usage-voice-chars", type=int, default=0, help="Premium voice chars to record as used")
    parser.add_argument(
        "--rollover-tokens", type=int, default=0, help="Initial rollover tokens (can be negative for debt)"
    )
    parser.add_argument("--rollover-voice-chars", type=int, default=0, help="Initial rollover voice chars")
    parser.add_argument("--advance-days", type=int, default=0, help="Advance clock by N days after setup")
    parser.add_argument("--skip-trial", action="store_true", help="Advance past trial immediately")
    parser.add_argument("--cleanup", metavar="CLOCK_ID", help="Delete a test clock instead of creating")
    parser.add_argument("--name", default="Billing Test", help="Test clock name")

    args = parser.parse_args()

    load_env()

    api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY not set", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key

    # Cleanup mode
    if args.cleanup:
        cleanup_clock(args.cleanup)
        return

    # Create test clock and resources
    clock = create_test_clock(args.name)
    customer = create_customer(clock.id)
    price_id = get_price_id(args.tier, args.interval)
    sub = create_subscription(customer.id, price_id, args.tier, args.trial_days)

    # Get subscription details
    sub = stripe.Subscription.retrieve(sub.id)
    user_id = sub.metadata.get("user_id")
    period_start = sub["items"].data[0].current_period_start
    period_end = sub["items"].data[0].current_period_end

    # Insert DB records
    conn = get_db_connection()
    try:
        plan_id = get_plan_id(args.tier, conn)
        insert_db_records(
            conn,
            user_id=user_id,
            plan_id=plan_id,
            tier=args.tier,
            customer_id=customer.id,
            subscription_id=sub.id,
            period_start=period_start,
            period_end=period_end,
            usage_tokens=args.usage_tokens,
            usage_voice_chars=args.usage_voice_chars,
            rollover_tokens=args.rollover_tokens,
            rollover_voice_chars=args.rollover_voice_chars,
        )
    finally:
        conn.close()

    # Advance clock if requested
    total_advance = args.advance_days
    if args.skip_trial:
        total_advance = max(total_advance, args.trial_days + 1)

    if total_advance > 0:
        advance_clock(clock.id, total_advance)

    # Print summary
    print("\n" + "=" * 60)
    print("TEST CLOCK SETUP COMPLETE")
    print("=" * 60)
    print(f"Clock ID:        {clock.id}")
    print(f"Customer ID:     {customer.id}")
    print(f"Subscription ID: {sub.id}")
    print(f"User ID:         {user_id}")
    print(f"Tier:            {args.tier}")
    print(
        f"Period:          {datetime.fromtimestamp(period_start, tz=timezone.utc)} to {datetime.fromtimestamp(period_end, tz=timezone.utc)}"
    )
    if args.usage_tokens or args.usage_voice_chars:
        print(f"Usage:           {args.usage_tokens} tokens, {args.usage_voice_chars} voice chars")
    if args.rollover_tokens or args.rollover_voice_chars:
        print(f"Rollover:        {args.rollover_tokens} tokens, {args.rollover_voice_chars} voice chars")
    print("=" * 60)
    print("\nNext steps:")
    print(f"  - Advance clock: uv run scripts/test_clock_setup.py --cleanup {clock.id}")
    print(f"  - Or use: stripe test_helpers test_clocks advance {clock.id} --frozen-time=TIMESTAMP")
    print(f"  - Check subscription: stripe subscriptions retrieve {sub.id}")
    print(
        f"  - Check DB: docker exec yapit-postgres-1 psql -U yapit -d yapit -c \"SELECT * FROM usersubscription WHERE user_id = '{user_id}'\""
    )


if __name__ == "__main__":
    main()
