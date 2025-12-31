# /// script
# requires-python = ">=3.12"
# dependencies = ["stripe"]
# ///
"""Stripe product and price provisioning script.

Creates subscription products and prices in Stripe. Idempotent - safe to re-run.

Usage:
    # Test mode (reads STRIPE_SECRET_KEY_TEST from .env)
    uv run scripts/stripe_setup.py --test

    # Production (decrypt sops first, or use sops exec-env)
    SOPS_AGE_KEY_FILE=... sops exec-env .env.sops 'uv run scripts/stripe_setup.py --prod'
"""

import argparse
import os
import sys

import stripe

TAX_CODE = "txcd_10103000"  # SaaS - personal use

PRODUCTS = [
    {
        "id": "yapit_basic",
        "name": "Yapit Basic",
        "description": "Unlimited server Kokoro, 500 OCR pages/month",
        "prices": [
            {"id": "yapit_basic_monthly", "amount": 700, "interval": "month"},
            {"id": "yapit_basic_yearly", "amount": 7500, "interval": "year"},
        ],
    },
    {
        "id": "yapit_plus",
        "name": "Yapit Plus",
        "description": "Everything in Basic + 20 hrs premium voice, 1500 OCR pages/month",
        "prices": [
            {"id": "yapit_plus_monthly", "amount": 2000, "interval": "month"},
            {"id": "yapit_plus_yearly", "amount": 19200, "interval": "year"},
        ],
    },
    {
        "id": "yapit_max",
        "name": "Yapit Max",
        "description": "Everything in Plus + 50 hrs premium voice, 3000 OCR pages/month",
        "prices": [
            {"id": "yapit_max_monthly", "amount": 4000, "interval": "month"},
            {"id": "yapit_max_yearly", "amount": 24000, "interval": "year"},
        ],
    },
]


def create_product(client: stripe.StripeClient, product: dict) -> str | None:
    """Create a product if it doesn't exist. Returns product ID."""
    product_id = product["id"]
    try:
        client.v1.products.create(
            {
                "id": product_id,
                "name": product["name"],
                "description": product["description"],
                "tax_code": TAX_CODE,
            }
        )
        print(f"  Created product: {product_id}")
        return product_id
    except stripe.InvalidRequestError as e:
        if "already exists" in str(e).lower():
            print(f"  Product exists: {product_id}")
            return product_id
        raise


def create_price(client: stripe.StripeClient, product_id: str, price: dict) -> str | None:
    """Create a price if it doesn't exist. Returns price ID."""
    price_id = price["id"]
    try:
        result = client.v1.prices.create(
            {
                "lookup_key": price_id,
                "product": product_id,
                "unit_amount": price["amount"],
                "currency": "eur",
                "recurring": {"interval": price["interval"]},
                "tax_behavior": "inclusive",
            }
        )
        print(f"    Created price: {price_id} -> {result.id}")
        return result.id
    except stripe.InvalidRequestError as e:
        if "already exists" in str(e).lower() or "lookup_key" in str(e).lower():
            prices = client.v1.prices.list({"lookup_keys": [price_id], "limit": 1})
            if prices.data:
                print(f"    Price exists: {price_id} -> {prices.data[0].id}")
                return prices.data[0].id
            print(f"    Warning: Price lookup failed for {price_id}: {e}")
            return None
        raise


def main():
    parser = argparse.ArgumentParser(description="Provision Stripe products and prices")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="Use test mode (STRIPE_SECRET_KEY_TEST)")
    group.add_argument("--prod", action="store_true", help="Use production mode (STRIPE_SECRET_KEY_LIVE)")
    args = parser.parse_args()

    secret_key = os.environ.get("STRIPE_SECRET_KEY")

    if not secret_key:
        print("Error: STRIPE_SECRET_KEY not set")
        print("\nUsage: uv run --env-file=.env scripts/stripe_setup.py --test")
        sys.exit(1)

    # Validate key matches mode
    is_test_key = secret_key.startswith("sk_test_")
    if args.test and not is_test_key:
        print("Error: STRIPE_SECRET_KEY does not look like a test key (should start with sk_test_)")
        sys.exit(1)
    if args.prod and is_test_key:
        print("Error: STRIPE_SECRET_KEY looks like a test key but --prod was specified")
        sys.exit(1)

    mode = "TEST" if args.test else "LIVE"
    print(f"\n{'=' * 50}")
    print(f"Stripe Product Setup ({mode} MODE)")
    print(f"{'=' * 50}\n")

    if args.prod:
        confirm = input("You are about to modify LIVE Stripe products. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    client = stripe.StripeClient(secret_key)
    price_ids: dict[str, str] = {}

    for product in PRODUCTS:
        print(f"\nProduct: {product['name']}")
        create_product(client, product)

        for price in product["prices"]:
            price_id = create_price(client, product["id"], price)
            if price_id:
                price_ids[price["id"]] = price_id

    print(f"\n{'=' * 50}")
    print("Price IDs for .env.dev / .env.prod:")
    print(f"{'=' * 50}")
    for lookup_key, stripe_id in sorted(price_ids.items()):
        env_var = lookup_key.upper().replace("YAPIT_", "STRIPE_PRICE_")
        print(f"  {env_var}={stripe_id}")

    print("\nAdd these to .env.dev (test) or .env.prod (live)")


if __name__ == "__main__":
    main()
