"""Create a user, or find the one holding this email, and mint it a new API token.

Prints the token on stdout and the user id on stderr, so `$(...)` captures just the token.
Writes straight to the database; it waits until the gateway has created its tables.

Examples:
    uv run python scripts/create_user.py
    uv run python scripts/create_user.py --email reader@example.com --name Reader --label laptop
    curl -H "Authorization: Bearer $(uv run python scripts/create_user.py 2>/dev/null)" localhost:8000/v1/auth/session
"""

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass

import tyro
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.accounts import normalize_email
from yapit.gateway.auth.sessions import create_api_token
from yapit.gateway.domain_models import UserAccount


@dataclass
class Args:
    email: str = "dev@example.com"
    """The user's email; an existing user with it gets the token."""
    name: str = "Dev User"
    """Display name for a user this creates."""
    label: str = "dev"
    """The API token's label."""
    database_url: str = "postgresql+asyncpg://yapit:yapit@localhost:5432/yapit"
    """The gateway's database (the dev Postgres by default)."""
    wait_s: int = 120
    """How long to wait for the gateway to create the useraccount table."""


async def create_user(args: Args) -> tuple[str, str]:
    """The user's id and a new API token for it."""
    engine = create_async_engine(args.database_url)
    try:
        await wait_for_tables(engine, args.wait_s)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            email = normalize_email(args.email)
            account = (await db.exec(select(UserAccount).where(UserAccount.email == email))).first()
            if account is None:
                account = UserAccount(id=str(uuid.uuid4()), email=email, name=args.name)
                db.add(account)
                await db.flush()
            token = create_api_token(db, account.id, args.label)
            await db.commit()
            return account.id, token
    finally:
        await engine.dispose()


async def wait_for_tables(engine: AsyncEngine, wait_s: int) -> None:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            async with engine.connect() as conn:
                if await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table("useraccount")):
                    return
        except (OSError, DBAPIError):
            pass  # Postgres not accepting connections yet
        if time.monotonic() > deadline:
            raise SystemExit(f"No useraccount table after {wait_s}s: is the gateway running?")
        await asyncio.sleep(1)


if __name__ == "__main__":
    user_id, token = asyncio.run(create_user(tyro.cli(Args, description=__doc__)))
    print(token)
    sys.stderr.write(user_id + "\n")
