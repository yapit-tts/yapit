# /// script
# requires-python = ">=3.12"
# dependencies = ["stripe"]
# ///
"""Stripe Infrastructure as Code - Products, Prices, Coupons, Promos, Portal.

This is the single source of truth for Stripe configuration. Running this script
applies the configuration to your Stripe account (test or live).

USAGE:
    # Test mode (reads STRIPE_SECRET_KEY from .env after make dev-env)
    uv run --env-file=.env scripts/stripe_setup.py --test

    # Production (decrypt sops first)
    SOPS_AGE_KEY_FILE=... sops exec-env .env.sops 'uv run scripts/stripe_setup.py --prod'

WHAT THIS SCRIPT DOES:
    1. VALIDATES config against Stripe (fails if immutable fields differ)
    2. Creates/updates Products (Basic, Plus, Max)
    3. Creates/updates Prices (monthly + yearly for each)
    4. Creates/updates Coupons (discount definitions)
    5. Creates/updates Promo Codes (customer-facing codes)
    6. Creates/updates Portal Configuration (customer self-service portal)

VALIDATION (FAIL-FAST):
    Before making ANY changes, the script checks all existing resources.
    If config differs from Stripe on immutable fields, the script FAILS
    without making any changes. This prevents partial updates.

MUTABLE VS IMMUTABLE FIELDS:
    Resource     | Mutable                    | Immutable (drift = error)
    -------------|----------------------------|------------------------------
    Product      | name, description, active  | id
    Price        | active, metadata           | amount, currency, interval
    Coupon       | name, metadata             | percent_off, amount_off, duration
    Promo Code   | active, metadata           | code, coupon, max_redemptions

    To change immutable fields: create new resource, update references, deactivate old.

DEACTIVATING RESOURCES:
    Set `active: False` in the config below, then run the script.
    Never delete - deactivate to preserve audit trail.

ADDING NEW COUPONS/PROMOS:
    1. Add coupon to COUPONS list below
    2. Add promo code to PROMO_CODES list below (referencing the coupon)
    3. Run: uv run --env-file=.env scripts/stripe_setup.py --test

PORTAL DOWNGRADES:
    Portal is configured with "immediately" for downgrades (not "schedule at period end").
    This works with Managed Payments. Our webhook handler detects the downgrade and sets
    grace_tier + grace_until so users keep higher-tier access until their paid period ends.
"""

import argparse
import os
import sys

import stripe

# =============================================================================
# CONFIGURATION - Edit these to change Stripe resources
# =============================================================================

TAX_CODE = "txcd_10103000"  # SaaS - personal use

PRODUCTS = [
    {
        "id": "yapit_basic",
        "name": "Yapit Basic",
        "description": "Unlimited server Kokoro, 500 OCR pages/month",
        "active": True,
        "prices": [
            {"id": "yapit_basic_monthly", "amount": 700, "interval": "month"},
            {"id": "yapit_basic_yearly", "amount": 7500, "interval": "year"},
        ],
    },
    {
        "id": "yapit_plus",
        "name": "Yapit Plus",
        "description": "Everything in Basic + 20 hrs premium voice, 1500 OCR pages/month",
        "active": True,
        "prices": [
            {"id": "yapit_plus_monthly", "amount": 2000, "interval": "month"},
            {"id": "yapit_plus_yearly", "amount": 19200, "interval": "year"},
        ],
    },
    {
        "id": "yapit_max",
        "name": "Yapit Max",
        "description": "Everything in Plus + 50 hrs premium voice, 3000 OCR pages/month",
        "active": True,
        "prices": [
            {"id": "yapit_max_monthly", "amount": 4000, "interval": "month"},
            {"id": "yapit_max_yearly", "amount": 24000, "interval": "year"},
        ],
    },
]

# Coupons define the discount. Promo codes are customer-facing codes that reference coupons.
COUPONS = [
    {
        "id": "beta_100",
        "name": "Beta - Free First Month",
        "percent_off": 100,
        "duration": "once",
        "active": True,
    },
    {
        "id": "launch_basic_100",
        "name": "Launch - Free Basic Month",
        "percent_off": 100,
        "duration": "once",
        "active": True,
    },
    {
        "id": "launch_plus_30",
        "name": "Launch Plus 30% Off",
        "percent_off": 30,
        "duration": "repeating",
        "duration_in_months": 3,
        "active": True,
    },
]

# Promo codes are what customers enter at checkout
PROMO_CODES = [
    {
        "coupon": "beta_100",
        "code": "BETA",
        "max_redemptions": 10,
        "active": True,  # Set False to deactivate at launch
    },
    {
        "coupon": "launch_basic_100",
        "code": "LAUNCH",
        "max_redemptions": 300,
        "active": True,
    },
    {
        "coupon": "launch_plus_30",
        "code": "LAUNCHPLUS",
        "max_redemptions": 100,
        "active": True,
    },
]

# Portal configuration - what customers can do in the self-service portal
# See: https://docs.stripe.com/api/customer_portal/configurations/create
PORTAL_CONFIG = {
    "business_profile": {
        "headline": "Manage your Yapit subscription",
        # privacy_policy_url and terms_of_service_url are set in Stripe Dashboard
        # under Settings > Public business information
    },
    "features": {
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "name", "address", "phone"],
        },
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive",
                    "missing_features",
                    "switched_service",
                    "unused",
                    "low_quality",
                    "too_complex",
                    "other",
                ],
            },
        },
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "proration_behavior": "create_prorations",
            # products array is populated dynamically after creating prices
        },
    },
    # default_return_url is set per-session in billing.py
}


# =============================================================================
# VALIDATION - Check for immutable field drift before making changes
# =============================================================================


def validate_prices(client: stripe.StripeClient) -> list[str]:
    """Check prices for immutable field drift. Returns list of errors."""
    errors = []
    for product in PRODUCTS:
        for price in product["prices"]:
            lookup_key = price["id"]
            existing_prices = client.v1.prices.list({"lookup_keys": [lookup_key], "limit": 1})
            if existing_prices.data:
                existing = existing_prices.data[0]
                if existing.unit_amount != price["amount"]:
                    errors.append(
                        f"Price {lookup_key}: amount is {existing.unit_amount} in Stripe, "
                        f"config says {price['amount']}. Create new price with different lookup_key."
                    )
                if existing.recurring and existing.recurring.interval != price["interval"]:
                    errors.append(
                        f"Price {lookup_key}: interval is '{existing.recurring.interval}' in Stripe, "
                        f"config says '{price['interval']}'. Create new price with different lookup_key."
                    )
    return errors


def validate_coupons(client: stripe.StripeClient) -> list[str]:
    """Check coupons for immutable field drift. Returns list of errors."""
    errors = []
    for coupon in COUPONS:
        coupon_id = coupon["id"]
        try:
            existing = client.v1.coupons.retrieve(coupon_id)
            if coupon.get("percent_off") and existing.percent_off != coupon["percent_off"]:
                errors.append(
                    f"Coupon {coupon_id}: percent_off is {existing.percent_off} in Stripe, "
                    f"config says {coupon['percent_off']}. Create new coupon with different ID."
                )
            if coupon.get("amount_off") and existing.amount_off != coupon["amount_off"]:
                errors.append(
                    f"Coupon {coupon_id}: amount_off is {existing.amount_off} in Stripe, "
                    f"config says {coupon['amount_off']}. Create new coupon with different ID."
                )
            if existing.duration != coupon.get("duration", "once"):
                errors.append(
                    f"Coupon {coupon_id}: duration is '{existing.duration}' in Stripe, "
                    f"config says '{coupon.get('duration', 'once')}'. Create new coupon with different ID."
                )
        except stripe.InvalidRequestError as e:
            if "No such coupon" not in str(e):
                raise
    return errors


def validate_promo_codes(client: stripe.StripeClient) -> list[str]:
    """Check promo codes for immutable field drift. Returns list of errors."""
    errors = []
    for promo in PROMO_CODES:
        code = promo["code"]
        existing_promos = client.v1.promotion_codes.list({"code": code, "limit": 1})
        if existing_promos.data:
            existing = existing_promos.data[0]
            # API returns promotion.coupon for the coupon ID
            existing_coupon_id = (
                existing.promotion.coupon
                if hasattr(existing, "promotion")
                else getattr(existing, "coupon", {}).get("id")
            )
            if existing_coupon_id != promo["coupon"]:
                errors.append(
                    f"Promo {code}: coupon is '{existing_coupon_id}' in Stripe, "
                    f"config says '{promo['coupon']}'. Create new promo code with different code."
                )
            if existing.max_redemptions != promo.get("max_redemptions"):
                errors.append(
                    f"Promo {code}: max_redemptions is {existing.max_redemptions} in Stripe, "
                    f"config says {promo.get('max_redemptions')}. Create new promo code with different code."
                )
    return errors


def validate_config(client: stripe.StripeClient) -> list[str]:
    """Run all validation checks. Returns list of all errors."""
    print("Validating configuration against Stripe...")
    errors = []
    errors.extend(validate_prices(client))
    errors.extend(validate_coupons(client))
    errors.extend(validate_promo_codes(client))
    return errors


# =============================================================================
# UPSERT FUNCTIONS - Create or update resources
# =============================================================================


def upsert_product(client: stripe.StripeClient, product: dict) -> str:
    """Create or update a product. Returns product ID."""
    product_id = product["id"]
    try:
        existing = client.v1.products.retrieve(product_id)
        updates = {}
        if existing.name != product["name"]:
            updates["name"] = product["name"]
        if existing.description != product.get("description"):
            updates["description"] = product.get("description")
        if existing.active != product.get("active", True):
            updates["active"] = product.get("active", True)

        if updates:
            client.v1.products.update(product_id, updates)
            print(f"  Updated product: {product_id} ({list(updates.keys())})")
        else:
            print(f"  Product unchanged: {product_id}")
        return product_id

    except stripe.InvalidRequestError as e:
        if "No such product" in str(e):
            client.v1.products.create(
                {
                    "id": product_id,
                    "name": product["name"],
                    "description": product.get("description"),
                    "tax_code": TAX_CODE,
                    "active": product.get("active", True),
                }
            )
            print(f"  Created product: {product_id}")
            return product_id
        raise


def upsert_price(client: stripe.StripeClient, product_id: str, price: dict) -> str | None:
    """Create or update a price. Returns Stripe price ID."""
    lookup_key = price["id"]
    existing_prices = client.v1.prices.list({"lookup_keys": [lookup_key], "limit": 1})

    if existing_prices.data:
        existing = existing_prices.data[0]
        stripe_id = existing.id

        # Update mutable fields only (immutable already validated)
        if existing.active != price.get("active", True):
            client.v1.prices.update(stripe_id, {"active": price.get("active", True)})
            print(f"    Updated price: {lookup_key} (active={price.get('active', True)})")
        else:
            print(f"    Price unchanged: {lookup_key} -> {stripe_id}")
        return stripe_id

    # Create new price
    result = client.v1.prices.create(
        {
            "lookup_key": lookup_key,
            "product": product_id,
            "unit_amount": price["amount"],
            "currency": "eur",
            "recurring": {"interval": price["interval"]},
            "tax_behavior": "inclusive",
            "active": price.get("active", True),
        }
    )
    print(f"    Created price: {lookup_key} -> {result.id}")
    return result.id


def upsert_coupon(client: stripe.StripeClient, coupon: dict) -> str:
    """Create or update a coupon. Returns coupon ID."""
    coupon_id = coupon["id"]

    try:
        existing = client.v1.coupons.retrieve(coupon_id)

        # Update mutable fields only (immutable already validated)
        updates = {}
        if existing.name != coupon.get("name"):
            updates["name"] = coupon.get("name")

        if updates:
            client.v1.coupons.update(coupon_id, updates)
            print(f"  Updated coupon: {coupon_id} ({list(updates.keys())})")
        else:
            print(f"  Coupon unchanged: {coupon_id}")
        return coupon_id

    except stripe.InvalidRequestError as e:
        if "No such coupon" in str(e):
            create_params = {
                "id": coupon_id,
                "name": coupon.get("name"),
                "duration": coupon.get("duration", "once"),
            }
            if coupon.get("percent_off"):
                create_params["percent_off"] = coupon["percent_off"]
            if coupon.get("amount_off"):
                create_params["amount_off"] = coupon["amount_off"]
                create_params["currency"] = coupon.get("currency", "eur")
            if coupon.get("duration") == "repeating":
                create_params["duration_in_months"] = coupon.get("duration_in_months", 1)

            client.v1.coupons.create(create_params)
            print(f"  Created coupon: {coupon_id}")
            return coupon_id
        raise


def upsert_promo_code(client: stripe.StripeClient, promo: dict) -> str | None:
    """Create or update a promo code. Returns promo code ID."""
    code = promo["code"]
    existing_promos = client.v1.promotion_codes.list({"code": code, "limit": 1})

    if existing_promos.data:
        existing = existing_promos.data[0]
        promo_id = existing.id

        # Update mutable fields only (immutable already validated)
        if existing.active != promo.get("active", True):
            client.v1.promotion_codes.update(promo_id, {"active": promo.get("active", True)})
            print(f"  Updated promo: {code} (active={promo.get('active', True)})")
        else:
            print(f"  Promo unchanged: {code} -> {promo_id}")
        return promo_id

    # Create new promo code
    # API uses promotion.coupon structure, not top-level coupon
    create_params = {
        "promotion": {"type": "coupon", "coupon": promo["coupon"]},
        "code": code,
        "active": promo.get("active", True),
    }
    if promo.get("max_redemptions"):
        create_params["max_redemptions"] = promo["max_redemptions"]
    if promo.get("expires_at"):
        create_params["expires_at"] = promo["expires_at"]
    if promo.get("restrictions"):
        create_params["restrictions"] = promo["restrictions"]

    result = client.v1.promotion_codes.create(create_params)
    print(f"  Created promo: {code} -> {result.id}")
    return result.id


def upsert_portal_config(client: stripe.StripeClient, config: dict, price_ids: dict[str, str]) -> str | None:
    """Create or update portal configuration. Returns config ID."""
    # Build products array for subscription_update
    products_config = []
    for product in PRODUCTS:
        if not product.get("active", True):
            continue
        product_prices = []
        for price in product["prices"]:
            if price["id"] in price_ids:
                product_prices.append(price_ids[price["id"]])
        if product_prices:
            products_config.append(
                {
                    "product": product["id"],
                    "prices": product_prices,
                }
            )

    # Build portal config with products
    portal_config = dict(config)
    portal_config["features"] = dict(config["features"])
    portal_config["features"]["subscription_update"] = dict(config["features"]["subscription_update"])
    portal_config["features"]["subscription_update"]["products"] = products_config

    # Check for existing portal configs
    existing_configs = client.v1.billing_portal.configurations.list({"limit": 10})

    # Find default config or first one
    existing = None
    for cfg in existing_configs.data:
        if cfg.is_default:
            existing = cfg
            break
    if not existing and existing_configs.data:
        existing = existing_configs.data[0]

    if existing:
        client.v1.billing_portal.configurations.update(existing.id, portal_config)
        print(f"  Updated portal config: {existing.id}")
        return existing.id
    else:
        result = client.v1.billing_portal.configurations.create(portal_config)
        print(f"  Created portal config: {result.id}")
        return result.id


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Stripe IaC - Products, Prices, Coupons, Promos, Portal")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="Use test mode (STRIPE_SECRET_KEY from .env)")
    group.add_argument("--prod", action="store_true", help="Use production mode (STRIPE_SECRET_KEY_LIVE)")
    args = parser.parse_args()

    secret_key = os.environ.get("STRIPE_SECRET_KEY")

    if not secret_key:
        print("Error: STRIPE_SECRET_KEY not set")
        print("\nUsage: uv run --env-file=.env scripts/stripe_setup.py --test")
        sys.exit(1)

    is_test_key = secret_key.startswith("sk_test_")
    if args.test and not is_test_key:
        print("Error: STRIPE_SECRET_KEY does not look like a test key (should start with sk_test_)")
        sys.exit(1)
    if args.prod and is_test_key:
        print("Error: STRIPE_SECRET_KEY looks like a test key but --prod was specified")
        sys.exit(1)

    mode = "TEST" if args.test else "LIVE"
    print(f"\n{'=' * 60}")
    print(f"Stripe Infrastructure Setup ({mode} MODE)")
    print(f"{'=' * 60}\n")

    if args.prod:
        confirm = input("You are about to modify LIVE Stripe configuration. Continue? [y/N] ")
        if confirm.lower() != "y":
            print("Aborted.")
            sys.exit(0)

    client = stripe.StripeClient(secret_key)

    # Phase 1: Validate (fail-fast if immutable fields differ)
    errors = validate_config(client)
    if errors:
        print(f"\n{'=' * 60}")
        print("VALIDATION FAILED - No changes made")
        print(f"{'=' * 60}")
        print("\nImmutable field drift detected:\n")
        for error in errors:
            print(f"  • {error}")
        print("\nFix the config or create new resources with different IDs.")
        sys.exit(1)

    print("Validation passed.\n")

    # Phase 2: Apply changes
    price_ids: dict[str, str] = {}

    print("Products & Prices:")
    for product in PRODUCTS:
        print(f"\n  {product['name']}:")
        upsert_product(client, product)

        for price in product["prices"]:
            price_id = upsert_price(client, product["id"], price)
            if price_id:
                price_ids[price["id"]] = price_id

    print("\n\nCoupons:")
    for coupon in COUPONS:
        upsert_coupon(client, coupon)

    print("\n\nPromo Codes:")
    for promo in PROMO_CODES:
        upsert_promo_code(client, promo)

    print("\n\nPortal Configuration:")
    upsert_portal_config(client, PORTAL_CONFIG, price_ids)

    # Summary
    print(f"\n{'=' * 60}")
    print("Price IDs for .env.dev / .env.prod:")
    print(f"{'=' * 60}")
    for lookup_key, stripe_id in sorted(price_ids.items()):
        env_var = lookup_key.upper().replace("YAPIT_", "STRIPE_PRICE_")
        print(f"  {env_var}={stripe_id}")

    print("\nAdd these to .env.dev (test) or .env.prod (live)")
    print("\nDone!")


if __name__ == "__main__":
    main()
