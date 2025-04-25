from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto

from sqlalchemy.orm import Mapped
from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """Platform user."""

    id: str | None = Field(default=None, primary_key=True)
    email: str
    tier: str = Field(default="free")  # todo why field?
    created: datetime = Field(default_factory=datetime.utcnow)

    jobs: Mapped[list[Job]] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Model(SQLModel, table=True):
    """A TTS model type."""

    id: str | None = Field(default=None, primary_key=True)
    description: str
    price_sec: float = 0.0

    voices: Mapped[list[Voice]] = Relationship(
        back_populates="model",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    jobs: Mapped[list[Job]] = Relationship(back_populates="model")


class Voice(SQLModel, table=True):
    """Concrete voice belonging to a model."""

    id: str | None = Field(default=None, primary_key=True)
    model_id: str | None = Field(foreign_key="model.id")

    name: str
    lang: str
    # xxx description / properties?

    model: Mapped[Model] = Relationship(back_populates="voices")
    jobs: Mapped[list[Job]] = Relationship(back_populates="voice")


class JobState(StrEnum):
    queued = auto()
    running = auto()
    finished = auto()
    cancelled = auto()
    failed = auto()


class Job(SQLModel, table=True):
    """High-level synthesis task covering N audio blocks."""

    id: str | None = Field(default=None, primary_key=True)

    user_id: str | None = Field(foreign_key="user.id", default=None)
    model_id: str | None = Field(foreign_key="model.id")
    voice_id: str | None = Field(foreign_key="voice.id")

    text_sha256: str
    speed: float
    codec: str
    est_sec: float

    state: JobState = JobState.queued
    created: datetime = Field(default_factory=datetime.utcnow)
    finished: datetime | None = None

    user: Mapped[User | None] = Relationship(back_populates="jobs")
    model: Mapped[Model] = Relationship(back_populates="jobs")
    voice: Mapped[Voice] = Relationship(back_populates="jobs")
    blocks: Mapped[list[Block]] = Relationship(
        back_populates="job", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class Block(SQLModel, table=True):
    """One audio chunk (≈10–20 s)."""

    id: str | None = Field(default=None, primary_key=True)
    job_id: str | None = Field(foreign_key="job.id")

    idx: int  # zero-based position in job
    sha256: str  # audio cache key
    duration_sec: float
    cached: bool = Field(default=False)

    deleted_at: datetime = None

    job: Mapped[Job] = Relationship(back_populates="blocks")
