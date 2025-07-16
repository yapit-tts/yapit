import datetime as dt
import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, auto
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel as PydanticModel
from pydantic import Field as PydanticField
from sqlalchemy import DECIMAL, Index, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlmodel import JSON, TEXT, Column, DateTime, Field, Relationship, SQLModel

# NOTE: Forward annotations do not work with SQLModel


class TTSModel(SQLModel, table=True):
    """A TTS model type."""

    id: int | None = Field(default=None, primary_key=True)

    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = Field(default=None)
    credit_multiplier: Decimal = Field(sa_column=Column(DECIMAL(10, 4), nullable=False, default=1.0))

    sample_rate: int
    channels: int
    sample_width: int
    native_codec: str

    voices: list["Voice"] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        },
    )
    block_variants: list["BlockVariant"] = Relationship(back_populates="model")


class Voice(SQLModel, table=True):
    """Concrete voice belonging to a model."""

    id: int | None = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="ttsmodel.id")

    slug: str
    name: str
    lang: str
    description: str | None = Field(default=None)

    model: TTSModel = Relationship(back_populates="voices")
    block_variants: list["BlockVariant"] = Relationship(back_populates="voice")

    __table_args__ = (UniqueConstraint("slug", "model_id", name="unique_voice_per_model"),)


class DocumentMetadata(TypedDict):
    """Metadata about a document."""

    content_type: str  # MIME type
    content_source: Literal["url", "upload", "text"]  # How we got the content

    total_pages: int  # 1 for websites and text
    file_size: NotRequired[float | None]  # File size in bytes (only for uploads)
    title: NotRequired[str | None]
    url: NotRequired[str | None]  # Original URL if from web
    filename: NotRequired[str | None]  # Original filename if uploaded


class Document(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field()

    title: str | None = Field(default=None)

    original_text: str = Field(sa_column=Column(TEXT))
    filtered_text: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))
    last_applied_filter_config: dict | None = Field(
        default=None,
        sa_column=Column(
            JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )

    source_ref: str | None = Field(default=None)  # URL or filename for extracted documents
    metadata_: DocumentMetadata | None = Field(  # name `metadata` reserved by SQLModel
        default=None,
        sa_column=Column(
            "metadata",
            JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )

    extraction_method: str | None = Field(default=None)  # processor slug used for extraction
    # Structured content for frontend display (XML with block tags, images, tables, etc.)
    structured_content: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    blocks: list["Block"] = Relationship(
        back_populates="document", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class Block(SQLModel, table=True):
    """A text block within a document, about 10-20 seconds of audio."""

    id: int | None = Field(default=None, primary_key=True)
    document_id: uuid.UUID = Field(foreign_key="document.id")

    idx: int  # zero-based position in document
    text: str = Field(sa_column=Column(TEXT))
    est_duration_ms: int | None = Field(default=None)  # 1x speed estimate based on text length

    document: Document = Relationship(back_populates="blocks")
    variants: list["BlockVariant"] = Relationship(
        back_populates="block", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class BlockVariant(SQLModel, table=True):
    """A synthesized audio variant of a text block."""

    hash: str = Field(primary_key=True)  # Hash(block.text, model, voice, speed, codec)

    block_id: int = Field(foreign_key="block.id")
    model_id: int = Field(foreign_key="ttsmodel.id")
    voice_id: int = Field(foreign_key="voice.id")
    speed: float
    codec: str

    duration_ms: int | None = Field(default=None)  # real duration of synthesized audio
    cache_ref: str | None = Field(default=None)  # FS path or S3 key

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    block: Block = Relationship(back_populates="variants")
    model: TTSModel = Relationship(back_populates="block_variants")
    voice: Voice = Relationship(back_populates="block_variants")

    @staticmethod
    def get_hash(text: str, model_slug: str, voice_slug: str, speed: float, codec: str) -> str:
        """Generates a unique hash for a given text block and synthesis parameters."""
        hasher = hashlib.sha256()
        hasher.update(text.encode("utf-8"))
        hasher.update(f"|{model_slug}".encode("utf-8"))
        hasher.update(f"|{voice_slug}".encode("utf-8"))
        hasher.update(f"|{speed:.2f}".encode("utf-8"))
        hasher.update(f"|{codec}".encode("utf-8"))
        return hasher.hexdigest()


class DocumentProcessor(SQLModel, table=True):
    """Available document processors for content extraction."""

    slug: str = Field(primary_key=True)
    name: str
    credits_per_page: Decimal = Field(sa_column=Column(DECIMAL(10, 4), nullable=False))  # cost

    max_pages: int
    max_file_size_mb: int
    supported_formats: list[str] = Field(sa_column=Column(postgresql.JSONB(), nullable=False))
    supports_batch: bool


class RegexRule(PydanticModel):
    pattern: str
    replacement: str


class FilterConfig(PydanticModel):
    regex_rules: list[RegexRule] = PydanticField(default_factory=list)
    llm: dict[str, Any] = PydanticField(default_factory=dict)


class Filter(SQLModel, table=True):
    """User or system defined reusable text filter configuration."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: str | None = Field(default=None, index=True)  # if null, readonly for non-admins

    name: str = Field(index=True)
    description: str | None = Field(default=None)
    config: FilterConfig = Field(
        sa_column=Column(
            JSON().with_variant(postgresql.JSONB(), "postgresql"),
        ),
        default_factory=FilterConfig,
    )

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )


# Billing Models


class TransactionType(StrEnum):
    credit_purchase = auto()  # User bought credits with real money
    credit_bonus = auto()  # Free credits (sign-up bonus, promotions, admin top-up)
    credit_refund = auto()  # Credits returned due to service issues
    credit_adjustment = auto()  # Manual admin corrections (errors, compensation)
    usage_deduction = auto()  # Credits consumed by TTS synthesis


class TransactionStatus(StrEnum):
    pending = auto()
    completed = auto()
    failed = auto()
    reversed = auto()


class UserCredits(SQLModel, table=True):
    """User's credit balance for TTS usage (in USD)."""

    user_id: str = Field(primary_key=True)  # Stack Auth user ID
    balance: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))

    total_purchased: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))
    total_used: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
    updated: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    transactions: list["CreditTransaction"] = Relationship(back_populates="user_credits")


class CreditTransaction(SQLModel, table=True):
    """Audit trail for all credit balance changes."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field(foreign_key="usercredits.user_id", index=True)

    type: TransactionType
    status: TransactionStatus = Field(default=TransactionStatus.pending)

    amount: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))
    balance_before: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))
    balance_after: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))

    description: str | None = Field(default=None)
    details: dict | None = Field(  # name `metadata` reserved by SQLModel
        default=None,
        sa_column=Column(postgresql.JSONB(), nullable=True),
    )

    # References to related records
    external_reference: str | None = Field(default=None, index=True)  # e.g., stripe_invoice_id
    usage_reference: str | None = Field(default=None, index=True)  # e.g., document_id or block_variant_hash

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    user_credits: UserCredits = Relationship(back_populates="transactions")

    __table_args__ = (
        Index("idx_credit_transaction_created", "created"),
        Index("idx_credit_transaction_user_created", "user_id", "created"),
    )


class CreditPackage(SQLModel, table=True):
    """Maps provider price IDs to credit amounts."""  # TODO do we even need this?

    id: int | None = Field(default=None, primary_key=True)
    provider_price_id: str = Field(unique=True, index=True)
    credits: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False))
    is_active: bool = Field(default=True)


class UserUsageStats(SQLModel, table=True):
    """Aggregated usage statistics for each user."""

    user_id: str = Field(primary_key=True, foreign_key="usercredits.user_id")

    total_seconds_synthesized: Decimal = Field(sa_column=Column(DECIMAL(19, 4), nullable=False, default=0))
    total_characters_processed: int = Field(default=0)
    total_requests: int = Field(default=0)

    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )
