---
status: done
type: implementation
---

# Task: Subscription Backend Refactor

**Knowledge extracted:** [[secrets-management]] (TEST/LIVE pattern), [[stripe-integration]] (Stripe patterns, Managed Payments, webhooks), [[architecture]] (updated billing models)

## Goal

Replace the credits-based billing system with subscription tiers. Users subscribe to a plan (Free/Basic/Premium/Power), get monthly usage limits, and limits reset each billing period.

Reference: [[pricing-strategy-rethink]] for tier structure and pricing decisions.

## Constraints / Design Decisions

1. **No backwards compatibility** — Can delete old credits tables, yeet volumes, reseed DB
2. **Subscription tiers over credits** — Usage limits, not pay-per-use
3. **Stripe Managed Payments** — Already decided, handles VAT/tax globally
4. **Premium voices = TTS API** — HIGGS shelved, simpler integration
5. **Limits must be enforced** — No manual tracking, hard limits in code

## Current State

### Database Models (`yapit/gateway/domain_models.py`)

**Credits system (to be removed):**
- `UserCredits` — balance, total_purchased, total_used
- `CreditTransaction` — audit log for balance changes
- `CreditPackage` — maps Stripe price IDs to credit amounts (unused)
- `TTSModel.credits_per_sec` — per-model pricing
- `DocumentProcessor.credits_per_page` — per-processor pricing
- `UserUsageStats` — aggregated usage (can repurpose)

### Billing API (`yapit/gateway/api/v1/billing.py`)

- `GET /v1/billing/packages` — hardcoded credit packs
- `POST /v1/billing/checkout` — Stripe Checkout (mode="payment")
- `POST /v1/billing/webhook` — handles `checkout.session.completed`
- `GET /v1/billing/checkout/{session_id}/status` — poll payment status

### Credit Deduction Points

**TTS synthesis** (`processors/tts/base.py:118-163`):
- After synthesis completes, calculates `duration_seconds × model.credits_per_sec`
- Updates `UserCredits.balance`, creates `CreditTransaction`

**Document processing** (`processors/document/base.py:166-225`):
- Pre-checks credits before processing
- Bills after processing: `num_pages × processor.credits_per_page`

**WebSocket credit check** (`api/v1/ws.py:248-251`):
- Simple `balance <= 0` check for server-side synthesis
- Admins bypass

## New Database Schema

### Plan (static reference data)

```python
class PlanTier(StrEnum):
    free = auto()
    basic = auto()
    plus = auto()
    max = auto()

class BillingInterval(StrEnum):
    monthly = auto()
    yearly = auto()

class Plan(SQLModel, table=True):
    """Available subscription plans."""
    id: int | None = Field(default=None, primary_key=True)
    tier: PlanTier = Field(unique=True, index=True)
    name: str  # "Basic", "Plus", "Max"

    # Limits per billing period (None = unlimited, 0 = not available)
    # Using characters (simpler, matches API billing, known upfront before synthesis)
    server_kokoro_characters: int | None = None  # null = unlimited
    premium_voice_characters: int | None = None  # ~17 chars = 1 second audio
    ocr_pages: int | None = None  # pages per period

    # Stripe price IDs (null for free tier)
    stripe_price_id_monthly: str | None = None
    stripe_price_id_yearly: str | None = None

    # Trial period (card-required, usage limits still apply)
    trial_days: int = 0  # 0 = no trial, 3 = 3-day trial

    # Display
    price_cents_monthly: int = 0
    price_cents_yearly: int = 0

    is_active: bool = True
```

### UserSubscription

```python
class SubscriptionStatus(StrEnum):
    active = auto()
    past_due = auto()
    canceled = auto()
    incomplete = auto()

class UserSubscription(SQLModel, table=True):
    """User's active subscription."""
    user_id: str = Field(primary_key=True)  # Stack Auth user ID
    plan_id: int = Field(foreign_key="plan.id")

    status: SubscriptionStatus = Field(default=SubscriptionStatus.active)

    # Stripe references
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    # Billing period (for usage tracking)
    current_period_start: datetime
    current_period_end: datetime

    # Cancellation
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None

    created: datetime
    updated: datetime

    plan: Plan = Relationship()
```

### UsagePeriod

```python
class UsagePeriod(SQLModel, table=True):
    """Usage counters for a billing period."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)

    period_start: datetime
    period_end: datetime

    # Counters (characters for TTS, pages for OCR)
    server_kokoro_characters: int = Field(default=0)
    premium_voice_characters: int = Field(default=0)
    ocr_pages: int = Field(default=0)

    # Indexes for efficient lookup
    __table_args__ = (
        Index("idx_usage_period_user_period", "user_id", "period_start"),
    )
```

### UsageLog (replaces CreditTransaction)

```python
class UsageType(StrEnum):
    server_kokoro = auto()
    premium_voice = auto()
    ocr = auto()

class UsageLog(SQLModel, table=True):
    """Immutable audit log for usage events."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field(index=True)

    type: UsageType
    amount: Decimal  # seconds for TTS, pages for OCR

    description: str | None = None
    details: dict | None = Field(sa_column=Column(postgresql.JSONB()))

    # Reference to what was used
    reference_id: str | None = None  # variant_hash, cache_key, etc.

    created: datetime
```

## API Changes

### New Endpoints

```
GET  /v1/billing/plans              # List available plans
GET  /v1/users/me/subscription      # Get current subscription + usage
POST /v1/billing/subscribe          # Create subscription checkout
POST /v1/billing/portal             # Get Stripe billing portal URL
POST /v1/billing/webhook            # Handle Stripe events (update)
```

### Stripe Checkout (Subscription Mode)

```python
@router.post("/subscribe")
async def create_subscription_checkout(
    request: SubscribeRequest,  # plan_tier, interval (monthly/yearly)
    http_request: Request,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> CheckoutResponse:
    plan = get_plan_by_tier(request.tier)
    price_id = plan.stripe_price_id_monthly if request.interval == "monthly" else plan.stripe_price_id_yearly

    # Get or create Stripe customer
    customer_id = await get_or_create_stripe_customer(user, db)

    # Build subscription_data with optional trial
    subscription_data = {"metadata": {"user_id": user.id, "plan_tier": plan.tier}}
    if plan.trial_days > 0:
        subscription_data["trial_period_days"] = plan.trial_days

    session = stripe.checkout.Session.create(
        mode="subscription",  # NOT "payment"
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        subscription_data=subscription_data,
        success_url=f"{origin}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin}/checkout/cancel",
        metadata={"user_id": user.id, "plan_tier": plan.tier},
    )
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)
```

### Stripe Billing Portal

```python
@router.post("/portal")
async def create_billing_portal_session(
    http_request: Request,
    settings: SettingsDep,
    user: AuthenticatedUser,
    db: DbSession,
) -> PortalResponse:
    subscription = await get_user_subscription(user.id, db)
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(400, "No active subscription")

    session = stripe.billing_portal.Session.create(
        customer=subscription.stripe_customer_id,
        return_url=f"{origin}/settings",
    )
    return PortalResponse(portal_url=session.url)
```

### Webhook Events to Handle

```python
SUBSCRIPTION_EVENTS = {
    "checkout.session.completed",      # New subscription created
    "customer.subscription.created",   # Subscription activated
    "customer.subscription.updated",   # Plan change, status change
    "customer.subscription.deleted",   # Canceled
    "invoice.payment_succeeded",       # Renewal succeeded (reset usage)
    "invoice.payment_failed",          # Payment failed
}

async def handle_subscription_webhook(event: dict, db: DbSession):
    event_type = event["type"]

    if event_type == "checkout.session.completed":
        # Create UserSubscription record
        session = event["data"]["object"]
        user_id = session["metadata"]["user_id"]
        subscription_id = session["subscription"]
        # Fetch subscription details from Stripe, create local record

    elif event_type == "customer.subscription.updated":
        # Update status, plan, period dates
        subscription = event["data"]["object"]
        # Sync to local UserSubscription

    elif event_type == "invoice.payment_succeeded":
        # New billing period started
        invoice = event["data"]["object"]
        if invoice.get("billing_reason") == "subscription_cycle":
            # Create new UsagePeriod, reset counters
            pass
```

## Usage Tracking & Enforcement

### Check Before Use

```python
async def check_usage_limit(
    user_id: str,
    usage_type: UsageType,
    amount: Decimal,
    db: AsyncSession,
) -> None:
    """Raise InsufficientUsageError if limit would be exceeded."""
    subscription = await get_user_subscription(user_id, db)
    if not subscription:
        subscription = get_free_plan_subscription()

    plan = subscription.plan
    usage = await get_current_usage_period(user_id, subscription, db)

    limit = getattr(plan, f"{usage_type}_limit")
    current = getattr(usage, usage_type)

    if limit is not None and current + amount > limit:
        raise UsageLimitExceededError(
            usage_type=usage_type,
            limit=limit,
            current=current,
            requested=amount,
        )
```

### Record After Use

```python
async def record_usage(
    user_id: str,
    usage_type: UsageType,
    amount: Decimal,
    reference_id: str | None,
    details: dict | None,
    db: AsyncSession,
) -> None:
    """Increment usage counter and create audit log."""
    usage = await get_current_usage_period(user_id, db)

    # Increment counter
    setattr(usage, usage_type, getattr(usage, usage_type) + amount)

    # Create audit log
    log = UsageLog(
        user_id=user_id,
        type=usage_type,
        amount=amount,
        reference_id=reference_id,
        details=details,
    )
    db.add(log)
    await db.commit()
```

### Integration Points

**TTS synthesis** (`processors/tts/base.py`):
```python
# Before synthesis (in WebSocket handler or processor):
await check_usage_limit(user_id, UsageType.premium_voice, estimated_seconds, db)

# After synthesis completes:
await record_usage(
    user_id=user_id,
    usage_type=UsageType.premium_voice,
    amount=duration_seconds,
    reference_id=variant_hash,
    details={"model": model_slug, "duration_ms": duration_ms},
    db=db,
)
```

**Document processing** (`processors/document/base.py`):
```python
# Before processing:
await check_usage_limit(user_id, UsageType.ocr, num_pages, db)

# After processing:
await record_usage(
    user_id=user_id,
    usage_type=UsageType.ocr,
    amount=pages_processed,
    reference_id=cache_key,
    details={"processor": processor_slug},
    db=db,
)
```

## Free Tier Handling

Users without a subscription default to Free tier:
- Browser Kokoro: unlimited (no usage tracking needed)
- Server Kokoro: not available (limit = 0)
- Premium voices: not available (limit = 0)
- OCR: not available (limit = 0)

```python
async def get_user_subscription(user_id: str, db: AsyncSession) -> UserSubscription | None:
    result = await db.exec(
        select(UserSubscription)
        .where(UserSubscription.user_id == user_id)
        .options(selectinload(UserSubscription.plan))
    )
    return result.first()

def get_effective_plan(subscription: UserSubscription | None) -> Plan:
    if subscription and subscription.status == SubscriptionStatus.active:
        return subscription.plan
    return FREE_PLAN  # Constant with free tier limits
```

## Migration Plan

### Database Migration

1. Create new tables: `Plan`, `UserSubscription`, `UsagePeriod`, `UsageLog`
2. Seed `Plan` with tier data:
   ```python
   # ~17 chars = 1 second of audio
   # 20 hrs = 1,224,000 chars, 50 hrs = 3,060,000 chars
   plans = [
       Plan(tier=PlanTier.free, name="Free", server_kokoro_characters=0, premium_voice_characters=0, ocr_pages=0, trial_days=0),
       Plan(tier=PlanTier.basic, name="Basic", server_kokoro_characters=None, premium_voice_characters=0, ocr_pages=500, trial_days=3, ...),
       Plan(tier=PlanTier.plus, name="Plus", server_kokoro_characters=None, premium_voice_characters=1_224_000, ocr_pages=1500, trial_days=3, ...),
       Plan(tier=PlanTier.max, name="Max", server_kokoro_characters=None, premium_voice_characters=3_060_000, ocr_pages=3000, trial_days=0, ...),
   ]
   ```
3. Drop old tables: `UserCredits`, `CreditTransaction`, `CreditPackage`
4. Remove `credits_per_sec` from `TTSModel`, `credits_per_page` from `DocumentProcessor`

### Code Changes (in order)

1. **Add new models** to `domain_models.py`
2. **Create migration** with alembic
3. **Update billing.py** — new endpoints, subscription checkout, webhook handler
4. **Add usage tracking functions** — `check_usage_limit`, `record_usage`
5. **Update TTS processor** — replace credit deduction with usage tracking
6. **Update document processor** — replace credit check/deduction
7. **Update WebSocket handler** — use new limit checking
8. **Update user endpoints** — `/me/subscription` instead of `/me/credits`
9. **Remove old code** — credit-related imports, functions, endpoints

### Stripe Setup (Manual)

1. Create Products in Stripe Dashboard:
   - Basic Monthly (€7), Basic Yearly (€75)
   - Premium Monthly (€20), Premium Yearly (€192)
   - Power Monthly (€40), Power Yearly (€240)
2. Get Price IDs, add to Plan seed data
3. Configure Billing Portal in Stripe Dashboard
4. Update webhook endpoint to handle subscription events

## Open Questions

1. **Upgrade/downgrade mid-period:** Prorate? Immediate? Start next period?
   - Stripe handles proration by default — probably fine

2. **What happens when subscription lapses?**
   - Move to Free tier
   - Keep documents accessible (browser Kokoro still works)
   - Just can't use premium features

3. **Trial period?**
   - Not initially. Maybe later.

4. **Annual subscription usage period:**
   - Still monthly usage resets? Or 12x limit for the year?
   - Probably monthly resets — simpler, prevents abuse

## Next Steps

After this task:
- [[subscription-frontend]] — Plan selection UI, usage display

---

## Notes / Findings

### Stripe Subscription Patterns

- Use `mode="subscription"` in Checkout Session
- Customer must exist in Stripe (create if needed)
- Webhook is the source of truth for subscription state
- Use Billing Portal for self-service management (cancel, update payment)
- `invoice.payment_succeeded` with `billing_reason="subscription_cycle"` = new period

### Key Webhook Events

- `checkout.session.completed` — subscription created via checkout
- `customer.subscription.updated` — catches most state changes
- `customer.subscription.deleted` — fully canceled
- `invoice.payment_succeeded` — new period, reset usage

### Free Trial Strategy

Replaces the old "signup bonus credits" approach. Card-required trial via Stripe:
- Basic: 3-day trial
- Plus: 3-day trial
- Max: No trial (for committed heavy users)

Usage limits still apply during trial — prevents abuse while letting users try premium features. Stripe handles trial → paid transition automatically; users can cancel before trial ends to avoid charge.

### Server Kokoro Handling

Server Kokoro has "unlimited" usage for paid tiers. Options:
1. Don't track at all (simplest)
2. Track but don't limit (for analytics)
3. Have a very high soft limit (abuse prevention)

Recommend #2 — track for analytics, don't enforce. Set `server_kokoro_characters = None` in Plan.

### Self-Hosting Support

App should work without Stripe for self-hosted deployments:

```python
# In config.py
billing_enabled: bool = True  # Set False for self-hosted

# In usage enforcement
if not settings.billing_enabled:
    return  # No limits in self-hosted mode
```

When `billing_enabled=False`:
- Skip all subscription/limit checks
- All users get unlimited access
- No Stripe integration needed
- Admin can still manually grant subscriptions for testing

### Stripe Tax / Managed Payments

Stripe Tax (automatic tax calculation) requires one API change:
```python
stripe.checkout.Session.create(
    automatic_tax={'enabled': True},  # Enable tax calculation
    ...
)
```

Rest is dashboard configuration (tax registrations, settings). Handle `invoice.finalization_failed` webhook if customer address is invalid.

### Characters vs Seconds Decision

Changed from seconds to characters for usage tracking:
- Characters match TTS API billing ($5/million chars)
- Known upfront before synthesis (can pre-check limits)
- Simpler — no need to wait for audio duration
- ~17 chars ≈ 1 second of audio

---

## Work Log

### 2025-12-30 - Task Created

Explored existing billing code:
- `domain_models.py`: UserCredits, CreditTransaction, CreditPackage, TTSModel.credits_per_sec
- `billing.py`: Stripe checkout (payment mode), webhook handler, packages endpoint
- `processors/tts/base.py`: Credit deduction after synthesis
- `processors/document/base.py`: Credit check before, deduction after
- `ws.py`: Simple balance check for server-side synthesis

Researched Stripe subscriptions:
- `mode="subscription"` in checkout.Session.create
- `stripe.billing_portal.Session.create` for self-service
- Key events: checkout.session.completed, customer.subscription.*, invoice.payment_succeeded

Designed new schema:
- Plan (static tiers), UserSubscription (user's active sub), UsagePeriod (monthly counters), UsageLog (audit)
- Replace credit balance with usage counters checked against plan limits

Ready for implementation.

### 2025-12-30 - Models Updated, Migration Blocked

**Completed:**
- Updated `domain_models.py` with new subscription models (Plan, UserSubscription, UsagePeriod, UsageLog)
- Removed old billing models (UserCredits, CreditTransaction, CreditPackage, TransactionType, TransactionStatus)
- Removed `credits_per_sec` from TTSModel
- Removed `credits_per_page` from DocumentProcessor
- Changed from seconds → characters for usage tracking
- Added Stripe research findings (trial periods, billing portal, webhooks)
- Added self-hosting support notes

**Blocked on migration:**
Attempted `make migration-new MSG="subscription refactor"` but failed because 11 files still import removed models:
- `yapit/gateway/db.py` - imports UserCredits
- `yapit/gateway/deps.py` - imports UserCredits, CreditTransaction
- `yapit/gateway/api/v1/billing.py` - entire file uses old credit system
- `yapit/gateway/api/v1/admin.py` - credit adjustment endpoints
- `yapit/gateway/api/v1/users.py` - /me/credits endpoint
- `yapit/gateway/api/v1/documents.py` - credit checks
- `yapit/gateway/processors/tts/base.py` - credit deduction after synthesis
- `yapit/gateway/processors/document/base.py` - credit checks and deduction
- `yapit/gateway/dev_seed.py` - seeds credit data

**Next steps:**
1. Fix import errors in 11 files (immediate blockers)
2. Audit ALL billing-related flows for credit assumptions:
   - WebSocket handler credit checks (`ws.py`)
   - Document upload flow (credit pre-check)
   - TTS synthesis flow (credit deduction)
   - Frontend API assumptions (`/me/credits`, `/billing/packages`, etc.)
   - Admin endpoints (credit grants, adjustments)
   - Checkout success page polling
3. Implement new usage tracking functions (check_usage_limit, record_usage)
4. Rewrite billing.py with subscription endpoints
5. Run migration: `make migration-new MSG="subscription refactor"`
6. Test with dev environment
7. Update frontend to use new endpoints (separate task?)

**Also document:** Migration workflow in CLAUDE.md (was requested)

**Files to audit beyond direct imports:**
- `yapit/gateway/api/v1/ws.py` - credit check logic in WebSocket
- `frontend/src/pages/CreditsPage.tsx` - entire page needs rework
- `frontend/src/pages/CheckoutSuccessPage.tsx` - polls old endpoint
- `frontend/src/components/documentSidebar.tsx` - shows credit balance
- Any other frontend components that display credits or call billing endpoints

### 2025-12-31 - Backend Implementation In Progress

**Completed:**
- Created `yapit/gateway/usage.py` — usage tracking service with:
  - `get_user_subscription()`, `get_effective_plan()`
  - `get_or_create_usage_period()` for subscribed users only
  - `check_usage_limit()` — raises UsageLimitExceededError if exceeded
  - `record_usage()` — increments counters + creates audit log
  - `get_usage_summary()` — returns plan/usage/limits for API
- Added `UsageLimitExceededError` to exceptions.py (replaces InsufficientCreditsError)
- Added `BillingInterval` enum to domain_models.py
- Fixed `db.py` — removed `get_or_create_user_credits`
- Fixed `deps.py` — removed credit-related imports and functions
- Fixed `dev_seed.py` — removed CreditPackage, credits_per_sec, credits_per_page; added Plan seeding
- Rewrote `billing.py` — new subscription endpoints using Stripe Managed Payments
- Fixed `admin.py` — removed credit adjustment endpoint
- Fixed `users.py` — replaced /me/credits with /me/subscription
- Started `documents.py` — updated prepare endpoints to not calculate credit costs

**Important discovery: Stripe Managed Payments**
User caught that I was using `automatic_tax: {'enabled': True}` (Stripe Tax) instead of `managed_payments: {'enabled': True}` (Managed Payments). These are different products:
- **Stripe Tax**: You're merchant of record, Stripe calculates tax
- **Managed Payments**: Stripe is merchant of record, handles VAT/tax globally, liability shifts to Stripe

Managed Payments requires:
- Beta version header: `stripe_version: "...; managed_payments_preview=v1"`
- Products with eligible tax codes in Stripe Dashboard
- See `agent/knowledge/private/stripe-managed-payments-documentation.md`

**Remaining files to fix:**
- `documents.py` — remove `ensure_admin_credits` dependency, update `create_document` endpoint
- `processors/tts/base.py` — replace credit deduction with `record_usage()`
- `processors/document/base.py` — replace credit check/deduction with usage tracking
- `ws.py` — replace credit balance check with `check_usage_limit()`

**Then:**
- Run migration
- Document migration workflow in CLAUDE.md
- Create separate task for frontend updates (CreditsPage → SubscriptionPage, etc.)

## Open Questions for Next Agent

### 1. Stripe Products/Prices IaC
The Managed Payments docs show product creation via API (see `agent/knowledge/private/stripe-managed-payments-documentation.md`). We should:
- Create a script to provision products/prices via API (version controlled)
- NOT do manual UI work in Stripe Dashboard

**Current state:** User already created Basic product with 2 prices (€7/mo, €75/yr) in PRODUCTION (non-sandbox). Product ID: `prod_ThcuO6dC3Tv1rB`, tax code: `txcd_10103000` (SaaS - personal use).

**Questions:**
- Keep the manually created prod product, or recreate via script?
- Script approach: one script that works for both test and prod by swapping API keys?
- What about existing subscriptions if we recreate products?

### 2. Dev/Test Strategy
- Stripe has test mode (sk_test_*) and live mode (sk_live_*)
- **Confirmed:** Test and live are completely separate environments
- **Confirmed:** Same script works for both, just swap API key
- Products/prices in test mode don't exist in live mode (separate)
- **Recommendation:** Create IaC script, run with test keys for dev, live keys for prod
- Since no active subscriptions exist, can delete manually-created Basic and recreate via script

### 3. Documentation Gaps - Need to Fetch
- Standard Stripe billing portal docs (for consistency with StripeClient)
- Standard Stripe webhook patterns
- Stripe test mode vs live mode behavior
- Managed Payments eligible tax codes list

### 4. Code Gaps Remaining
- `documents.py` - remove ensure_admin_credits, update create_document
- `processors/tts/base.py` - replace credit deduction with record_usage()
- `processors/document/base.py` - replace credit check/deduction
- `ws.py` - replace credit balance check with check_usage_limit()
- `billing.py` - update portal to use StripeClient (consistency)
- Create Stripe product/price provisioning script

### 5. Tax Code for Managed Payments
From user's screenshot: using `txcd_10103000` (SaaS - personal use). Need to verify this is correct for all tiers and eligible for Managed Payments.

### 2025-12-31 - Research Complete, Ready for Implementation

**Research conducted on Stripe best practices:**

#### Idempotent Product/Price Creation Scripts
From [Stripe product management docs](https://docs.stripe.com/products-prices/manage-prices?dashboard-or-api=api):
- **Scripts CAN be made idempotent** using pattern: try create → catch "already exists" → update instead
- Use stable product IDs (e.g., `yapit_basic`, `yapit_plus`) to enable idempotency
- Prices can only update `metadata`, `nickname`, `active` after creation — so check existence first, skip if already created
- Idempotency keys supported for POST requests (255 chars max, 24h expiry in API v1, 30 days in v2)

Source: [Stripe Idempotent Requests](https://docs.stripe.com/api/idempotent_requests)

#### Billing Portal StripeClient Pattern
From [Stripe API Reference](https://docs.stripe.com/api/customer_portal/sessions/create):
```python
# Correct pattern (StripeClient v1 namespace):
client = stripe.StripeClient(settings.stripe_secret_key)
session = client.v1.billing_portal.sessions.create({
    "customer": customer_id,
    "return_url": return_url,
})
```
The current billing.py `/portal` endpoint uses old module-level pattern — needs update for consistency.

#### Managed Payments Requirements
From local docs (`agent/knowledge/private/stripe-managed-payments-documentation.md`):
- **API Version**: `2025-03-31.basil` or later (examples use `2025-05-28.basil`)
- **Beta Header**: `; managed_payments_preview=v1` appended to stripe_version
- **Tax Code**: `txcd_10103000` (SaaS - personal use) confirmed eligible
- **Checkout params**: `managed_payments: {"enabled": True}`

#### Stripe API Key Security Decision
- **Both test and live keys stay in `.env.sops` (encrypted)**
- Provisioning script takes `--test-env` or `--prod-env` flag, reads appropriate key from sops
- Contributors can either: (a) get sops access, or (b) create own Stripe test account and run script with their own keys
- Rationale: Even test keys allow full API access (create/delete products, subscriptions, etc.)

#### Stripe Product IaC Strategy
- **Delete manually-created Basic product, recreate all via script**
- Script creates all 4 products (Free metadata-only, Basic, Plus, Max) with prices
- Idempotent: can re-run safely (checks existence before create)
- Same script works for test and prod by swapping API key via flag

**Files remaining to fix:**
1. `documents.py` — `ensure_admin_credits`, `_calculate_credit_cost` functions
2. `processors/tts/base.py` — credit deduction logic, old model imports
3. `processors/document/base.py` — `UserCredits`, `InsufficientCreditsError`, credit check/deduction
4. `ws.py` — `get_or_create_user_credits` import, credit balance check
5. `billing.py` — portal endpoint needs StripeClient pattern

**Current billing.py status:**
- `/subscribe` — ✅ Correct (StripeClient + Managed Payments)
- `/portal` — ✅ Fixed (now uses StripeClient)
- `/webhook` — ✅ OK (module-level is standard for webhooks)

### 2025-12-31 - Backend Files Fixed, Ready for Migration

**All 5 files fixed:**

1. **documents.py** ✅
   - Removed `ensure_admin_credits` dependency
   - Removed `user_credits` parameter from `create_document`
   - Removed `user_credits=user_credits` from processor call
   - Added `DocumentProcessor` import for `__name__` usage
   - Deleted `_calculate_document_credit_cost` and `_calculate_credit_cost` functions

2. **processors/tts/base.py** ✅
   - Removed old imports: `Decimal`, `datetime`, `selectinload`, `select`, `CreditTransaction`, `TransactionStatus`, `TransactionType`, `UserUsageStats`, `get_or_create_user_credits`
   - Added: `UsageType` from domain_models, `record_usage` from usage.py
   - Replaced credit deduction logic (lines 145-198) with `record_usage()` call
   - Usage type determined by model slug: `kokoro*` → server_kokoro, else → premium_voice

3. **processors/document/base.py** ✅
   - Removed: `Decimal`, `CreditTransaction`, `DocumentProcessor`, `TransactionType`, `UserCredits`, `InsufficientCreditsError`, `get_by_slug_or_404`
   - Added: `UsageType` from domain_models, `check_usage_limit`, `record_usage` from usage.py
   - Removed `user_credits` parameter from `process_with_billing`
   - Replaced credit check with `check_usage_limit(user_id, UsageType.ocr, len(uncached_pages), db)`
   - Replaced `_create_transaction` call with `record_usage()`
   - Deleted `_create_transaction` method

4. **ws.py** ✅
   - Removed: `get_or_create_user_credits` import
   - Added: `UsageType`, `UsageLimitExceededError`, `check_usage_limit`
   - Moved block fetch before usage check (needed for character count estimation)
   - Replaced credit balance check with `check_usage_limit()` using actual character count

5. **billing.py** ✅
   - `/portal` endpoint now uses StripeClient pattern: `client.v1.billing_portal.sessions.create({...})`

**Imports verified working:** `python -c "from yapit.gateway.api.v1 import documents, billing, ws; ..."` passes

**Next:** Run `make migration-new MSG="subscription refactor"` to generate migration for new tables (Plan, UserSubscription, UsagePeriod, UsageLog)

**Then:** Create Stripe product/price provisioning script (idempotent, `--test-env`/`--prod-env` flags)

**Side task created:** [[user-stats-analytics]] for profile page stats and analytics brainstorming

### 2025-12-31 - Migration Complete, Handover

**Migration generated successfully:**
- File: `yapit/gateway/migrations/versions/d29aaf752330_subscription_refactor.py`
- Added tables: `plan`, `usagelog`, `usageperiod`, `usersubscription`
- Removed columns: `documentprocessor.credits_per_page`, `ttsmodel.credits_per_sec`

**Migration workflow documented in CLAUDE.md** - covers dev flow (`make migration-new`) and prod deployment (automatic via `alembic upgrade head` on gateway startup).

**To apply locally:** `make dev-cpu`

**To deploy to prod:** Normal `scripts/deploy.sh` — migration runs automatically on gateway startup.

---

## Remaining Work

### Integration Tests — Need Holistic Review

**Failing tests (reference old credit system):**
```
tests/integration/test_documents.py::test_prepare_and_process_with_markitdown - KeyError: 'credit_cost'
tests/integration/test_tts_billing.py::test_tts_insufficient_credits - AssertionError (expects "insufficient credits", now "usage limit exceeded")
tests/integration/test_tts_billing.py::test_tts_with_credits_deduction - 404 (old endpoint?)
tests/integration/test_tts_billing.py::test_tts_cached_no_credit_deduction - 404 (old endpoint?)
```

**Approach:**
1. Read through `tests/integration/` to understand what's there
2. Delete tests for removed functionality (credit purchases, credit deductions)
3. Update tests that can be adapted (error message changes, endpoint changes)
4. Add new tests for subscription/usage system:
   - User with no subscription → free tier limits
   - User with subscription → plan limits apply
   - Usage recording after TTS synthesis
   - Webhook handling (subscription created, updated, canceled)

### Stripe Setup (User Actions)

1. ✅ Keys added to `.env.sops` with `_TEST`/`_LIVE` pattern
2. ✅ Live key has IP restriction to prod server
3. Run `scripts/stripe_setup.py --test` → get test price IDs
4. Update `dev_seed.py` with test price IDs
5. Delete manually-created Basic product in Stripe prod dashboard
6. Run `scripts/stripe_setup.py --prod` from server → get prod price IDs
7. Set up webhook endpoints in Stripe Dashboard (test + prod)
8. Add `STRIPE_WEBHOOK_SECRET_TEST` and `STRIPE_WEBHOOK_SECRET_LIVE` to `.env.sops`

### Frontend (Separate Task)

- Replace CreditsPage with SubscriptionPage
- Update billing UI to show plan/usage instead of credits
- Update checkout flow for subscriptions

### Stripe API Key Security Note

- Live key has IP restriction to prod server IP (Hetzner)
- Test key unrestricted (sandboxed, need flexibility during dev)
- For `stripe_setup.py --prod`: run from prod server via SSH (already has correct env)

### 2025-12-31 - Migration Workflow Fix

**Issue:** Previous documentation implied needing postgres running from before schema changes. User identified this as brittle — if you accidentally run `make dev-cpu` mid-refactor, postgres dies and `migration-new` fails.

**Fix:** Updated `make migration-new` to auto-start postgres if not running:
```makefile
@docker compose ... ps postgres ... | grep -q "Up" || \
    (echo "Starting postgres..." && docker compose ... up -d postgres --wait)
```

**Result:** Migration workflow is now self-contained. No prior state needed — just:
1. Make your model changes + update all code that references them
2. Run `make migration-new MSG="..."` — starts postgres automatically
3. Run `make dev-cpu` to apply

Updated CLAUDE.md with simplified docs reflecting this.

### 2025-12-31 - Stripe Provisioning Script Created

Created `scripts/stripe_setup.py`:
- Mandatory `--test` / `--prod` flag (no accidental prod operations)
- Reads `STRIPE_SECRET_KEY_TEST` or `STRIPE_SECRET_KEY_LIVE` from env
- Validates key prefix matches mode
- Creates 4 products with tax code `txcd_10103000` (SaaS - personal use)
- Creates monthly + yearly prices for paid tiers (Basic €7/€75, Plus €20/€192, Max €40/€240)
- Idempotent via Stripe `lookup_key` pattern
- Outputs price IDs to update in `dev_seed.py`

### 2025-12-31 - Secrets Management & Test Fixes

**Secrets flow refactored:**
- `.env.sops` now has `*_TEST` and `*_LIVE` variants for Stripe keys
- `make dev-env` (renamed from env-dev) transforms `*_TEST` → main var, removes `*_LIVE` and `STACK_*`
- Documented in CLAUDE.md under "Secrets Management"
- Updated `.env.template` to show the `_TEST`/`_LIVE` pattern

**Unit test fixes completed:**
- `test_admin.py`: Removed `UserCredits` import, `credits_per_sec` fields, credit management tests
- `test_users.py`: Removed all credit tests, kept filter tests
- `test_models.py`: Removed `credits_per_sec` from TTSModel instances
- `test_documents.py`: Removed `credit_cost` assertions, deleted redundant test
- `models.py` (API): Removed `credits_per_sec` from `ModelRead` schema
- `documents.py` (API): Added `_needs_ocr_processing()` helper — `uncached_pages` only returned for PDFs/images, not text files

**Unit tests passing:** `tests/yapit/gateway/api/test_documents.py` — 29 passed

### 2025-12-31 - Backend Complete, Stripe Configured

**Integration tests fixed:**
- `test_documents.py`: Removed `credit_cost` assertions (field no longer exists)
- `test_tts_billing.py`: Rewrote entirely — now tests usage limit error and cache behavior
- Added note about cache-hit-no-usage being verified by code inspection (behavioral test only)

**Self-hosting support added:**
- Added `billing_enabled: bool` to `config.py`
- Added to `.env.dev` and `.env.template` with documentation
- `check_usage_limit()` skips all checks when `billing_enabled=False`
- Self-hosters set `BILLING_ENABLED=false` for unlimited access without Stripe

**Stripe test environment configured:**
- Ran `scripts/stripe_setup.py --test` — created products/prices
- Updated `dev_seed.py` with test price IDs
- Production webhook configured at `https://yapit.md/v1/billing/webhook` (6 events)
- Webhook secret saved to `.env.sops`

**All tests passing.**

### 2025-12-31 - Bug Fix: Document Processor Usage Check

**Issue:** Dragging markdown files into frontend returned 402 (Payment Required) for free/guest users.

**Root cause:** `check_usage_limit(UsageType.ocr, ...)` ran for ALL document processors, including markitdown (free). Should only run for paid processors like mistral-ocr.

**Fix:**
- Added `is_paid` property to `BaseDocumentProcessor` (defaults to `False`)
- Only check/record usage when `self.is_paid` is `True`
- `MistralOCRProcessor` overrides `is_paid = True`

### 2025-12-31 - Bug Fixes and Testing Verification

**Fixes applied:**

1. **Admin bypass bug in document processor** — `process_with_billing()` wasn't passing `is_admin` to `check_usage_limit()`, so admins hit OCR limits. Fixed by:
   - Added `is_admin: bool = False` parameter to `process_with_billing()`
   - Added `IsAdmin` dependency to `create_document` endpoint
   - Passed `is_admin=is_admin` through to `check_usage_limit()`

2. **Test isolation issue** — `test_submit_audio_and_retrieve` used `regular_document` fixture (fixed text "Hello, I need credits!") which caused hash collisions with stale `BlockVariant` records. Fixed by using `unique_document` fixture (timestamp-based unique text).

**All tests passing:** 102 unit tests, 13 integration tests.

**Stripe webhook testing:**

Confirmed best practice via Stripe docs: **webhooks are the authoritative source**, not client-side polling. The frontend shouldn't poll a checkout status endpoint — it should:
1. Show success message after redirect
2. Optionally poll `/v1/users/me/subscription` to confirm webhook processed

For local dev testing: `nix run nixpkgs#stripe-cli -- listen --forward-to localhost:8000/v1/billing/webhook`

**Frontend work needed** (part of [[subscription-frontend]]):
- `CheckoutSuccessPage.tsx` still polls old `/checkout/{session_id}/status` endpoint
- Should poll `/v1/users/me/subscription` instead

**Code changes not yet in running backend** — need `make dev-cpu` to pick up:
- Admin bypass fix in `processors/document/base.py`
- `IsAdmin` dependency in `documents.py`

**Next steps for handover:**
1. Restart backend: `make dev-cpu`
2. Test webhook flow with stripe listen running
3. Commit the bug fixes

---

## Status: Done

**Next:** [[subscription-frontend]] — Plan selection UI, usage display, checkout flow

**Before prod deployment:**
- Test full checkout flow locally with `stripe listen` forwarding webhooks
- Run `scripts/stripe_setup.py --prod` from prod server
- Verify webhook receives events

---

## Key Learnings

### Stripe Setup Pattern
- Products/prices created via `scripts/stripe_setup.py` (idempotent via lookup_key)
- Test and prod are separate Stripe environments — same script, different `STRIPE_SECRET_KEY`
- Webhook signing secret is per-endpoint (different for test CLI vs prod dashboard)

### Self-Hosting Support
- `BILLING_ENABLED=false` disables all subscription/usage limits
- Self-hosters get unlimited access without Stripe
- Config flag checked in `check_usage_limit()` — early return if disabled

### Document Processor Billing
- `is_paid` property on processors determines if usage is tracked
- Markitdown = free (no tracking), Mistral-OCR = paid (counts against `ocr_pages` limit)
- Usage check happens in `process_with_billing()` before actual processing

### Free Tier Behavior
- No `UserSubscription` record = falls back to `FREE_PLAN` constant
- Free limits: `server_kokoro_characters=0`, `premium_voice_characters=0`, `ocr_pages=0`
- Browser TTS always works (no server-side limits apply)

### Stripe API 2025-03-31+ Breaking Change: Subscription Billing Periods

**Critical:** In API version 2025-03-31.basil and later, `current_period_start` and `current_period_end` were **removed from the subscription level** and moved to **subscription items**.

**Old pattern (broken):**
```python
period_start = stripe_sub.current_period_start  # AttributeError!
```

**New pattern (required):**
```python
first_item = stripe_sub["items"].data[0]  # API response
# or
first_item = stripe_sub["items"]["data"][0]  # Webhook dict
period_start = first_item.current_period_start
```

**Why:** Stripe now supports mixed-interval subscriptions where different items can have different billing periods.

**Source:** [Stripe Changelog - Deprecate subscription-level periods](https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end)

**Affects:**
- `_handle_checkout_completed()` - uses StripeClient, access via `.data[0].attr`
- `_handle_subscription_updated()` - uses webhook dict, access via `["data"][0]["key"]`
- Any code that retrieves subscriptions and accesses billing periods

### 2026-01-01 - Webhook End-to-End Test

**What we tested:** Full checkout → webhook → subscription creation flow

**How we tested:**
1. Started `stripe listen --forward-to http://localhost:8000/v1/billing/webhook` (via nix) for local webhook forwarding
2. Called `/v1/billing/subscribe` API to get checkout URL
3. Completed Stripe Checkout with test card (4242...) via Chrome DevTools MCP
4. Verified webhook received and processed

**Bugs found & fixed:**

1. **Missing API key in StripeClient call** (`billing.py:251`)
   - `stripe.Subscription.retrieve()` → `client.v1.subscriptions.retrieve()`
   - Root cause: Mixed module-level `stripe.*` calls with `StripeClient` pattern

2. **Stripe API 2025-03-31 breaking change** (`billing.py:266, 313`)
   - `current_period_start`/`current_period_end` moved from subscription level to subscription items
   - Fix: `first_item = stripe_sub["items"].data[0]` then `first_item.current_period_start`
   - Different access patterns: StripeClient returns objects (`.data[0].attr`), webhook dicts (`["data"][0]["key"]`)

**Verification:** Subscription created in DB with status=trialing, correct 3-day trial period.

**Dev testing notes:**
- stripe-cli added to docker-compose.dev.yml — auto-forwards webhooks to gateway (uses dashboard webhook secret from .env)
- Shell escaping with zsh: `TOKEN=$(curl ...)` inline assignment fails with parse errors. Workaround: write to file first, then read.
- Docker code mounting: dev compose only mounts JSON configs, not Python. Restart != rebuild. `make dev-cpu` needed after code changes.

**Code quality:** Backend is good to go. Changes minimal and correct per Stripe docs. No refactoring needed.

**Remaining work:**
- [[subscription-frontend]] — Plan selection UI, usage display (blocked - old endpoints called)

### 2025-12-31 - Archived

Knowledge extracted for future agents:
- Updated [[secrets-management]] with TEST/LIVE key pattern and `make dev-env` transformation
- Created [[stripe-integration]] (in private/) with Managed Payments patterns, webhook handling, IaC strategy
- Updated [[architecture]] with new billing models, removed credit references
