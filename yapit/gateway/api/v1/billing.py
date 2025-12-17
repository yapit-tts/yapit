from decimal import Decimal
from enum import StrEnum, auto

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import select

from yapit.gateway.deps import (
    AuthenticatedUser,
    DbSession,
    SettingsDep,
    get_or_create_user_credits,
)
from yapit.gateway.domain_models import (
    CreditTransaction,
    TransactionStatus,
    TransactionType,
)

router = APIRouter(prefix="/v1/billing", tags=["Billing"])


class CreditPackId(StrEnum):
    starter = auto()
    standard = auto()
    pro = auto()


class CreditPack(BaseModel):
    id: CreditPackId
    name: str
    credits: int
    price_cents: int
    currency: str


CREDIT_PACKS: dict[CreditPackId, CreditPack] = {
    CreditPackId.starter: CreditPack(
        id=CreditPackId.starter,
        name="Starter",
        credits=5000,
        price_cents=200,
        currency="eur",
    ),
    CreditPackId.standard: CreditPack(
        id=CreditPackId.standard,
        name="Standard",
        credits=15000,
        price_cents=500,
        currency="eur",
    ),
    CreditPackId.pro: CreditPack(
        id=CreditPackId.pro,
        name="Pro",
        credits=50000,
        price_cents=1200,
        currency="eur",
    ),
}


class CheckoutRequest(BaseModel):
    package_id: CreditPackId


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class CheckoutStatusResponse(BaseModel):
    status: TransactionStatus
    credits: int | None = None


@router.get("/packages")
async def list_packages() -> list[CreditPack]:
    """List available credit packages."""
    return list(CREDIT_PACKS.values())


@router.post("/checkout")
async def create_checkout_session(
    request: CheckoutRequest,
    http_request: Request,
    settings: SettingsDep,
    user: AuthenticatedUser,
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for credit purchase."""
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured",
        )

    pack = CREDIT_PACKS.get(request.package_id)
    if not pack:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid package ID")

    stripe.api_key = settings.stripe_secret_key

    origin = http_request.headers.get("origin", "").rstrip("/")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing origin header")
    success_url = f"{origin}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/checkout/cancel"

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": pack.currency,
                    "unit_amount": pack.price_cents,
                    "product_data": {
                        "name": f"Yapit Credits - {pack.name}",
                        "description": f"{pack.credits:,} credits for TTS synthesis",
                    },
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=user.primary_email,
        metadata={
            "user_id": user.id,
            "package_id": pack.id,
            "package_name": pack.name,
            "credits": str(pack.credits),
            "price_cents": str(pack.price_cents),
            "currency": pack.currency,
        },
    )

    assert session.url is not None
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    settings: SettingsDep,
    db: DbSession,
) -> dict:
    """Handle Stripe webhook events."""
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing is not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session = event["data"]["object"]
        await _fulfill_credits(session, db)

    return {"status": "ok"}


async def _fulfill_credits(session: dict, db: DbSession) -> None:
    """Add credits to user after successful payment."""
    session_id = session["id"]
    metadata = session.get("metadata", {})
    credits = int(metadata.get("credits", 0))
    user_id = metadata.get("user_id")
    package_name = metadata.get("package_name", "Unknown")

    if not credits or not user_id:
        return

    # Check if already processed (idempotency)
    result = await db.exec(select(CreditTransaction).where(CreditTransaction.external_reference == session_id))
    if result.first():
        return

    user_credits = await get_or_create_user_credits(user_id, db)

    # Create completed transaction
    transaction = CreditTransaction(
        user_id=user_id,
        type=TransactionType.credit_purchase,
        amount=Decimal(credits),
        balance_before=user_credits.balance,
        description=f"Credit purchase - {package_name}",
        external_reference=session_id,
        status=TransactionStatus.completed,
    )

    user_credits.balance += Decimal(credits)
    user_credits.total_purchased += Decimal(credits)
    transaction.balance_after = user_credits.balance

    db.add(transaction)
    await db.commit()


@router.get("/checkout/{session_id}/status")
async def get_checkout_status(
    session_id: str,
    db: DbSession,
    user: AuthenticatedUser,
) -> CheckoutStatusResponse:
    """Check the status of a checkout session."""
    result = await db.exec(
        select(CreditTransaction).where(
            CreditTransaction.external_reference == session_id,
            CreditTransaction.user_id == user.id,
        )
    )
    transaction = result.first()

    if not transaction:
        # No transaction yet = webhook hasn't processed the payment
        return CheckoutStatusResponse(status=TransactionStatus.pending)

    return CheckoutStatusResponse(
        status=transaction.status,
        credits=int(transaction.amount) if transaction.status == TransactionStatus.completed else None,
    )
