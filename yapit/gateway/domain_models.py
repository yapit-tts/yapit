import datetime as dt
import hashlib
import uuid
from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel as PydanticModel
from pydantic import computed_field
from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import JSON
from sqlmodel import TEXT, Column, DateTime, Field, Relationship, SQLModel

from yapit.gateway.constants import estimate_duration_ms

# NOTE: Forward annotations do not work with SQLModel


class TTSModel(SQLModel, table=True):
    """A TTS model type."""

    id: int | None = Field(default=None, primary_key=True)

    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = Field(default=None)

    sample_rate: int
    channels: int
    sample_width: int
    native_codec: str
    usage_multiplier: float = Field(default=1.0)
    is_active: bool = Field(default=True, index=True)

    voices: list["Voice"] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        },
    )
    block_variants: list["BlockVariant"] = Relationship(back_populates="model")


class Voice(SQLModel, table=True):
    """Concrete voice / synthesis parameterse belonging to a model."""

    id: int | None = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="ttsmodel.id")

    slug: str
    name: str
    lang: str | None  # None -> multilingual
    description: str | None = Field(default=None)
    is_active: bool = Field(default=True, index=True)

    parameters: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False)
    )

    model: TTSModel = Relationship(back_populates="voices")
    block_variants: list["BlockVariant"] = Relationship(back_populates="voice")

    __table_args__ = (UniqueConstraint("slug", "model_id", name="unique_voice_per_model"),)


class DocumentMetadata(PydanticModel):
    """Metadata about a document."""

    content_type: str  # MIME type
    total_pages: int  # 1 for websites and text
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    file_name: str | None = Field(default=None, max_length=255)
    file_size: int | None = None  # Content size in bytes


class Document(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field()
    is_public: bool = Field(default=False)

    title: str | None = Field(default=None, max_length=500)

    original_text: str = Field(sa_column=Column(TEXT))
    last_applied_filter_config: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )

    extraction_method: str | None = Field(default=None)  # processor slug used for extraction
    content_hash: str | None = Field(default=None, index=True)  # SHA256 of source content, for image cleanup
    # Structured content for frontend display (XML with block tags, images, tables, etc.)
    structured_content: str = Field(sa_column=Column(TEXT, nullable=False))

    # Cross-device sync: playback position
    last_block_idx: int | None = Field(default=None)
    last_played_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    blocks: list["Block"] = Relationship(
        back_populates="document", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    metadata_dict: dict | None = Field(  # Store as dict in DB - using different field name
        default=None,
        sa_column=Column(
            "metadata",
            JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )

    @property
    def metadata_(self) -> DocumentMetadata | None:  # name `metadata` reserved by SQLModel
        return DocumentMetadata(**self.metadata_dict) if self.metadata_dict else None

    @metadata_.setter
    def metadata_(self, value: DocumentMetadata | None) -> None:
        self.metadata_dict = value.model_dump() if value else None


class Block(SQLModel, table=True):
    """A text block within a document, about 10-20 seconds of audio."""

    id: int | None = Field(default=None, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="document.id")

    idx: int  # zero-based position in document
    text: str = Field(sa_column=Column(TEXT))

    document: Document = Relationship(back_populates="blocks")

    @computed_field
    @property
    def est_duration_ms(self) -> int:
        return estimate_duration_ms(len(self.text))


class BlockVariant(SQLModel, table=True):
    """Cached audio metadata, keyed by content hash (text + model + voice + params)."""

    hash: str = Field(primary_key=True)

    model_id: int = Field(foreign_key="ttsmodel.id")
    voice_id: int = Field(foreign_key="voice.id")

    duration_ms: int | None = Field(default=None)  # real duration of synthesized audio
    cache_ref: str | None = Field(default=None)  # FS path or S3 key

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    model: TTSModel = Relationship(back_populates="block_variants")
    voice: Voice = Relationship(back_populates="block_variants")

    @staticmethod
    def get_hash(text: str, model_slug: str, voice_slug: str, codec: str, parameters: dict) -> str:
        hasher = hashlib.sha256()
        hasher.update(text.encode("utf-8"))
        hasher.update(f"|{model_slug}".encode("utf-8"))
        hasher.update(f"|{voice_slug}".encode("utf-8"))
        hasher.update(f"|{codec}".encode("utf-8"))
        for key, value in sorted(parameters.items()):
            hasher.update(f"|{key}={value}".encode("utf-8"))
        return hasher.hexdigest()


class DocumentProcessor(SQLModel, table=True):
    """Available document processors for content extraction."""

    slug: str = Field(primary_key=True)
    name: str
    is_active: bool = Field(default=True, index=True)


# Subscription Models


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
    name: str

    # Limits per billing period (None = unlimited, 0 = not available)
    server_kokoro_characters: int | None = Field(default=None)
    premium_voice_characters: int | None = Field(default=None)
    ocr_tokens: int | None = Field(default=None)  # Token equivalents (processor-specific calculation)

    # Stripe price IDs (None for free tier)
    stripe_price_id_monthly: str | None = Field(default=None)
    stripe_price_id_yearly: str | None = Field(default=None)

    # Trial period (card-required, usage limits still apply)
    trial_days: int = Field(default=0)

    # Display pricing (in cents)
    price_cents_monthly: int = Field(default=0)
    price_cents_yearly: int = Field(default=0)

    is_active: bool = Field(default=True)


class SubscriptionStatus(StrEnum):
    active = auto()
    trialing = auto()
    past_due = auto()
    canceled = auto()
    incomplete = auto()


class UserSubscription(SQLModel, table=True):
    """User's active subscription."""

    user_id: str = Field(primary_key=True)  # Stack Auth user ID
    plan_id: int = Field(foreign_key="plan.id")

    status: SubscriptionStatus = Field(default=SubscriptionStatus.active)

    # Stripe references
    stripe_customer_id: str | None = Field(default=None, index=True)
    stripe_subscription_id: str | None = Field(default=None, unique=True, index=True)

    # Current billing period (for usage tracking)
    current_period_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    current_period_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))

    # Cancellation
    cancel_at_period_end: bool = Field(default=False)
    cancel_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    canceled_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    @property
    def is_canceling(self) -> bool:
        """True if subscription will cancel (either via cancel_at_period_end or cancel_at)."""
        if self.cancel_at_period_end:
            return True
        if self.cancel_at and self.cancel_at <= self.current_period_end:
            return True
        return False

    # Trial eligibility: highest tier ever subscribed (for per-tier trial logic)
    highest_tier_subscribed: PlanTier | None = Field(default=None)

    ever_paid: bool = Field(default=False)

    # Grace period: higher-tier access after downgrade (until period ends)
    grace_tier: PlanTier | None = Field(default=None)
    grace_until: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # Rollover: unused subscription tokens/chars carried forward (capped)
    rollover_tokens: int = Field(default=0)  # Capped at 10M
    rollover_voice_chars: int = Field(default=0)  # Capped at 1M

    # Purchased: from token/voice packs (uncapped, persists after cancellation)
    purchased_tokens: int = Field(default=0)
    purchased_voice_chars: int = Field(default=0)

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    plan: Plan = Relationship(sa_relationship_kwargs={"lazy": "selectin"})


class UsagePeriod(SQLModel, table=True):
    """Usage counters for a billing period."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)

    period_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    period_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))

    # Counters (characters for TTS, token equivalents for OCR)
    server_kokoro_characters: int = Field(default=0)
    premium_voice_characters: int = Field(default=0)
    ocr_tokens: int = Field(default=0)  # Token equivalents consumed this period

    __table_args__ = (
        UniqueConstraint("user_id", "period_start", name="uq_usage_period_user_period"),
        Index("idx_usage_period_user_period", "user_id", "period_start"),
    )


class UsageType(StrEnum):
    server_kokoro = auto()
    premium_voice = auto()
    ocr_tokens = auto()


class UsageLog(SQLModel, table=True):
    """Immutable audit log for usage events (character equivalents for TTS, token equivalents for OCR)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field(index=True)

    type: UsageType
    amount: int  # character equivalents for TTS, token equivalents for OCR

    description: str | None = Field(default=None)
    details: dict | None = Field(
        default=None,
        sa_column=Column(postgresql.JSONB(), nullable=True),
    )

    # Reference to what was used (variant_hash, cache_key, etc.)
    reference_id: str | None = Field(default=None, index=True)

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    __table_args__ = (
        Index("idx_usage_log_created", "created"),
        Index("idx_usage_log_user_created", "user_id", "created"),
    )


class UserPreferences(SQLModel, table=True):
    """User-synced preferences (cross-device)."""

    user_id: str = Field(primary_key=True)
    pinned_voices: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
    )

    auto_import_shared_documents: bool = Field(default=False)  # skip banner, auto-clone on visit
    default_documents_public: bool = Field(default=False)  # new docs created with is_public=True

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
