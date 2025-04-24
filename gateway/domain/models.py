from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto

from sqlalchemy import Column, Enum
from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    """Platform user."""

    id: str = Field(primary_key=True)
    email: str
    tier: str = Field(default="free")
    created: datetime = Field(default_factory=datetime.utcnow)

    jobs: list[Job] = Relationship(back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class Model(SQLModel, table=True):
    """A TTS model type."""

    id: str = Field(primary_key=True)
    description: str
    price_sec: float = Field(default=0.0)

    voices: list[Voice] = Relationship(back_populates="model", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    jobs: list[Job] = Relationship(back_populates="model")


class Voice(SQLModel, table=True):
    """Concrete voice belonging to a model."""

    id: str = Field(primary_key=True)
    model_id: str = Field(foreign_key="model.id")

    name: str
    lang: str
    # xxx description / properties?

    model: Model = Relationship(back_populates="voices")
    jobs: list[Job] = Relationship(back_populates="voice")


class JobState(StrEnum):
    queued = auto()
    running = auto()
    finished = auto()
    cancelled = auto()
    failed = auto()


class Job(SQLModel, table=True):
    """High-level synthesis task covering N audio blocks."""

    id: str = Field(primary_key=True)

    user_id: str | None = Field(foreign_key="user.id")
    model_id: str = Field(foreign_key="model.id")
    voice_id: str = Field(foreign_key="voice.id")

    text_sha256: str
    speed: float
    codec: str
    est_sec: float

    state: JobState = Field(
        sa_column=Column(Enum(JobState)),
        default=JobState.queued,
    )

    created: datetime = Field(default_factory=datetime.utcnow)
    finished: datetime | None = None

    user: User | None = Relationship(back_populates="jobs")
    model: Model = Relationship(back_populates="jobs")
    voice: Voice = Relationship(back_populates="jobs")
    blocks: list[Block] = Relationship(
        back_populates="job",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Block(SQLModel, table=True):
    """One audio chunk (≈10–20 s)."""

    id: str = Field(primary_key=True)
    job_id: str = Field(foreign_key="job.id")

    idx: int  # zero-based position in job
    sha256: str  # audio cache key
    duration_sec: float
    cached: bool = Field(default=False)

    deleted_at: datetime = None

    # Relationship
    job: Job = Relationship(back_populates="blocks")
