import datetime as dt
import hashlib
from datetime import datetime

import stripe
from fastapi import APIRouter, Header, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlmodel import delete, select

from yapit.gateway.auth import ANONYMOUS_ID_PREFIX
from yapit.gateway.deps import AuthenticatedUser, DbSession, SettingsDep
from yapit.gateway.domain_models import (
    Block,
    Document,
    SubscriptionStatus,
    UsageLog,
    UsagePeriod,
    UserPreferences,
    UserSubscription,
)
from yapit.gateway.stack_auth.users import delete_user as stack_auth_delete_user
from yapit.gateway.usage import get_usage_summary, get_user_subscription

router = APIRouter(prefix="/v1/users", tags=["Users"])


@router.get("/me/subscription")
async def get_my_subscription(
    db: DbSession,
    auth_user: AuthenticatedUser,
) -> dict:
    """Get current user's subscription and usage summary."""
    return await get_usage_summary(auth_user.id, db)


# Cross-device sync: User preferences


class PreferencesResponse(BaseModel):
    pinned_voices: list[str]
    auto_import_shared_documents: bool
    default_documents_public: bool


class PreferencesUpdate(BaseModel):
    pinned_voices: list[str] | None = None
    auto_import_shared_documents: bool | None = None
    default_documents_public: bool | None = None


@router.get("/me/preferences", response_model=PreferencesResponse)
async def get_preferences(
    auth_user: AuthenticatedUser,
    db: DbSession,
) -> PreferencesResponse:
    """Get user preferences for cross-device sync."""
    prefs = await db.get(UserPreferences, auth_user.id)
    if not prefs:
        return PreferencesResponse(
            pinned_voices=[],
            auto_import_shared_documents=False,
            default_documents_public=False,
        )
    return PreferencesResponse(
        pinned_voices=prefs.pinned_voices,
        auto_import_shared_documents=prefs.auto_import_shared_documents,
        default_documents_public=prefs.default_documents_public,
    )


@router.patch("/me/preferences", response_model=PreferencesResponse)
async def update_preferences(
    body: PreferencesUpdate,
    auth_user: AuthenticatedUser,
    db: DbSession,
) -> PreferencesResponse:
    """Update user preferences for cross-device sync."""
    prefs = await db.get(UserPreferences, auth_user.id)
    if not prefs:
        prefs = UserPreferences(user_id=auth_user.id)
        db.add(prefs)

    if body.pinned_voices is not None:
        prefs.pinned_voices = body.pinned_voices
    if body.auto_import_shared_documents is not None:
        prefs.auto_import_shared_documents = body.auto_import_shared_documents
    if body.default_documents_public is not None:
        prefs.default_documents_public = body.default_documents_public
    prefs.updated = datetime.now(tz=dt.UTC)

    await db.commit()
    await db.refresh(prefs)
    return PreferencesResponse(
        pinned_voices=prefs.pinned_voices,
        auto_import_shared_documents=prefs.auto_import_shared_documents,
        default_documents_public=prefs.default_documents_public,
    )


# User stats


class UserStatsResponse(BaseModel):
    total_audio_ms: int
    total_characters: int
    document_count: int


@router.get("/me/stats", response_model=UserStatsResponse)
async def get_user_stats(
    auth_user: AuthenticatedUser,
    db: DbSession,
) -> UserStatsResponse:
    """Get user's lifetime usage stats."""
    # Total audio duration and character count from blocks in user's documents
    stats_result = await db.exec(
        select(
            func.coalesce(func.sum(Block.est_duration_ms), 0),
            func.coalesce(func.sum(func.length(Block.text)), 0),
        )
        .join(Document)
        .where(Document.user_id == auth_user.id)
    )
    total_audio_ms, total_characters = stats_result.one()

    doc_count_result = await db.exec(select(func.count(Document.id)).where(Document.user_id == auth_user.id))
    document_count = doc_count_result.one()

    return UserStatsResponse(
        total_audio_ms=total_audio_ms,
        total_characters=total_characters,
        document_count=document_count,
    )


# Guest-to-registered conversion


class ClaimResponse(BaseModel):
    claimed_documents: int


@router.post("/claim-anonymous", response_model=ClaimResponse)
async def claim_anonymous_data(
    auth_user: AuthenticatedUser,
    db: DbSession,
    x_anonymous_id: str | None = Header(None, alias="X-Anonymous-ID"),
) -> ClaimResponse:
    """Transfer documents from anonymous session to authenticated user.

    Called by frontend after user signs up, to claim any data created while anonymous.
    """
    if auth_user.is_anonymous or not x_anonymous_id:
        return ClaimResponse(claimed_documents=0)

    anon_user_id = f"{ANONYMOUS_ID_PREFIX}{x_anonymous_id}"

    doc_result = await db.exec(update(Document).where(Document.user_id == anon_user_id).values(user_id=auth_user.id))

    await db.commit()

    claimed_docs = doc_result.rowcount if doc_result.rowcount else 0

    if claimed_docs:
        logger.info(f"User {auth_user.id} claimed {claimed_docs} docs from {anon_user_id}")

    return ClaimResponse(claimed_documents=claimed_docs)


# Account deletion


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    request: Request,
    auth_user: AuthenticatedUser,
    db: DbSession,
    settings: SettingsDep,
) -> None:
    """Delete user account and anonymize billing data.

    This action is irreversible. Deletes:
    - All documents (cascades to blocks and block variants)
    - User preferences

    Anonymizes (for aggregate analysis):
    - Subscription records
    - Usage periods
    - Usage logs
    """
    user_id = auth_user.id
    anon_id = f"deleted-{hashlib.sha256(user_id.encode()).hexdigest()[:12]}"

    # 1. Cancel Stripe subscription if active
    sub = await get_user_subscription(user_id, db)
    if sub and sub.stripe_subscription_id and sub.status in (SubscriptionStatus.active, SubscriptionStatus.trialing):
        if settings.stripe_secret_key:
            try:
                client = stripe.StripeClient(settings.stripe_secret_key)
                client.v1.subscriptions.cancel(sub.stripe_subscription_id)
                logger.info(f"Canceled Stripe subscription {sub.stripe_subscription_id} for user deletion")
            except stripe.InvalidRequestError as e:
                logger.warning(f"Failed to cancel Stripe subscription: {e}")

    # 2. Delete user-owned data (cascades handle blocks → block variants)
    await db.exec(delete(Document).where(Document.user_id == user_id))
    await db.exec(delete(UserPreferences).where(UserPreferences.user_id == user_id))

    # 3. Anonymize billing data (preserves patterns for aggregate analysis)
    await db.exec(update(UserSubscription).where(UserSubscription.user_id == user_id).values(user_id=anon_id))
    await db.exec(update(UsagePeriod).where(UsagePeriod.user_id == user_id).values(user_id=anon_id))
    await db.exec(update(UsageLog).where(UsageLog.user_id == user_id).values(user_id=anon_id))

    await db.commit()

    # 4. Delete from Stack Auth
    access_token = request.headers.get("authorization", "").removeprefix("Bearer ")
    try:
        await stack_auth_delete_user(settings, access_token, user_id)
        logger.info(f"Deleted user {user_id} from Stack Auth")
    except Exception as e:
        logger.error(f"Failed to delete user from Stack Auth: {e}")
        # Don't fail the request - data is already cleaned up

    logger.info(f"Account deletion complete for user {user_id} (anonymized as {anon_id})")
