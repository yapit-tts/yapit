# /// script
# requires-python = ">=3.12"
# dependencies = ["stripe", "python-dotenv"]
# ///
"""Read-only Stripe config inspection. Shows portal config and subscription update settings.

Usage:
    uv run --env-file=.env scripts/stripe_inspect.py
"""

import os
import sys

import stripe
from dotenv import load_dotenv


def main():
    load_dotenv()
    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    if not secret_key:
        print("Error: STRIPE_SECRET_KEY not set")
        sys.exit(1)

    mode = "TEST" if secret_key.startswith("sk_test_") else "LIVE"
    print(f"Stripe config inspection ({mode})\n{'=' * 50}\n")

    client = stripe.StripeClient(secret_key)

    # Portal configurations
    configs = client.v1.billing_portal.configurations.list({"limit": 10})
    if not configs.data:
        print("No portal configurations found.")
        return

    for cfg in configs.data:
        print(f"Portal config: {cfg.id} (default={cfg.is_default})")

        sub_update = cfg.features.subscription_update
        if sub_update:
            # Dump raw structure so we see exactly what the SDK returns
            print(f"  subscription_update: {sub_update}")
        else:
            print("  subscription_update: disabled")

        sub_cancel = cfg.features.subscription_cancel
        if sub_cancel:
            print(f"  subscription_cancel.enabled: {sub_cancel.enabled}")
            print(f"  subscription_cancel.mode: {sub_cancel.mode}")

        print()

    # Webhook endpoints
    print("Webhook endpoints:")
    webhooks = client.v1.webhook_endpoints.list({"limit": 10})
    for wh in webhooks.data:
        print(f"  {wh.url}")
        print(f"    events: {sorted(wh.enabled_events or [])}")
        print()


if __name__ == "__main__":
    main()
