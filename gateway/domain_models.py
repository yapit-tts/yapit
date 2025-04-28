import datetime as dt
import uuid
from datetime import datetime
from enum import StrEnum, auto

from sqlmodel import TEXT, Column, DateTime, Field, Relationship, SQLModel

# NOTE: Forward annotations do not work with SQLModel


class User(SQLModel, table=True):
    """Platform user."""

    id: str | None = Field(default=None, primary_key=True)
    email: str
    tier: str = Field(default="free")
    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    documents: list["Document"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Model(SQLModel, table=True):
    """A TTS model type."""

    id: int | None = Field(default=None, primary_key=True)

    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = Field(default=None)
    price_sec: float = 0.0

    voices: list["Voice"] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    block_variants: list["BlockVariant"] = Relationship(back_populates="model")


class Voice(SQLModel, table=True):
    """Concrete voice belonging to a model."""

    id: int | None = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="model.id")

    slug: str = Field(unique=True)
    name: str
    lang: str
    # xxx description / properties?

    model: Model = Relationship(back_populates="voices")
    block_variants: list["BlockVariant"] = Relationship(back_populates="voice")


class SourceType(StrEnum):
    url = auto()
    upload = auto()
    paste = auto()


class Document(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field(foreign_key="user.id")

    source_ref: str | None = Field(default=None)
    source_type: SourceType | None = Field(default=None)

    title: str | None = Field(default=None)

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    user: User = Relationship(back_populates="documents")
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


class BlockVariantState(StrEnum):
    pending = auto()  # synthesis job not yet queued
    queued = auto()  # synthesis job queued
    processing = auto()  # synthesis job started
    cached = auto()  # synthesis successful, audio stored
    failed = auto()  # synthesis attempted but failed


class BlockVariant(SQLModel, table=True):
    """A synthesized audio variant of a text block."""

    audio_hash: str = Field(primary_key=True)  # Hash(block.text, model_id, voice_id, speed, codec)

    block_id: int = Field(foreign_key="block.id")
    model_id: int = Field(foreign_key="model.id")
    voice_id: int = Field(foreign_key="voice.id")
    speed: float
    codec: str

    state: BlockVariantState = Field(default=BlockVariantState.pending)
    duration_ms: int | None = Field(default=None)  # real duration of synthesized audio
    cache_ref: str | None = Field(default=None)  # FS path or S3 key

    created: datetime = Field(
        default_factory=lambda: datetime.now(tz=dt.UTC),
        sa_column=Column(DateTime(timezone=True)),
    )

    block: Block = Relationship(back_populates="variants")
    model: Model = Relationship(back_populates="block_variants")
    voice: Voice = Relationship(back_populates="block_variants")
