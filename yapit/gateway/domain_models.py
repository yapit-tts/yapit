import datetime as dt
import hashlib
import uuid
from datetime import datetime
from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel as PydanticModel, Field as PydanticField
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import JSON, TEXT, Column, DateTime, Field, Relationship, SQLModel

# NOTE: Forward annotations do not work with SQLModel


class TTSModel(SQLModel, table=True):
    """A TTS model type."""

    id: int | None = Field(default=None, primary_key=True)

    slug: str = Field(unique=True, index=True)
    name: str
    description: str | None = Field(default=None)
    price_sec: float = 0.0

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


class SourceType(StrEnum):
    url = auto()
    upload = auto()
    paste = auto()


class Document(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: str = Field()

    source_ref: str | None = Field(default=None)
    source_type: SourceType | None = Field(default=None)

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
