import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.domain_models import UserAccount


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def sign_in_by_email(db: AsyncSession, email: str, now: datetime, name: str | None = None) -> UserAccount:
    """The account holding this (already proven) address, created on its first sign-in. Leaves the commit to the caller."""
    return (
        await db.exec(
            insert(UserAccount)
            .values(id=str(uuid.uuid4()), email=normalize_email(email), name=name, created=now, last_sign_in=now)
            .on_conflict_do_update(index_elements=["email"], set_={"last_sign_in": now})
            .returning(UserAccount)
        )
    ).scalar_one()
