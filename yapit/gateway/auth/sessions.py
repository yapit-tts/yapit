import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Response
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.config import Settings
from yapit.gateway.domain_models import AuthSession, AuthSessionKind, UserAccount

SIGN_IN_PENDING_COOKIE = "yapit_signin_pending"
SESSION_LIFETIME = timedelta(days=30)
SESSION_RENEW_BELOW = timedelta(days=15)
API_TOKEN_PREFIX = "yapit_"

# last_used is for display, so a write per request would buy nothing
LAST_USED_RESOLUTION = timedelta(hours=1)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass
class FoundSession:
    session: AuthSession
    user: UserAccount
    renewed: bool


def create_browser_session(db: AsyncSession, user_id: str) -> tuple[str, datetime]:
    """A new session for the cookie, and when it expires: the token goes to the browser, only its hash is stored."""
    token = new_secret()
    expires = datetime.now(tz=dt.UTC) + SESSION_LIFETIME
    db.add(AuthSession(token_hash=hash_secret(token), user_id=user_id, kind=AuthSessionKind.browser, expires=expires))
    return token, expires


def create_api_token(db: AsyncSession, user_id: str, label: str) -> str:
    token = API_TOKEN_PREFIX + new_secret()
    db.add(AuthSession(token_hash=hash_secret(token), user_id=user_id, kind=AuthSessionKind.api, label=label))
    return token


async def find_session(db: AsyncSession, token: str, kind: AuthSessionKind) -> FoundSession | None:
    """The live session this token opens, renewing a browser session that has under SESSION_RENEW_BELOW left."""
    row = (
        await db.exec(
            select(AuthSession, UserAccount)
            .join(UserAccount, col(UserAccount.id) == col(AuthSession.user_id))
            .where(AuthSession.token_hash == hash_secret(token), AuthSession.kind == kind)
        )
    ).first()
    if row is None:
        return None
    session, user = row
    now = datetime.now(tz=dt.UTC)
    if session.expires is not None and session.expires <= now:
        return None

    renewed = session.expires is not None and session.expires - now < SESSION_RENEW_BELOW
    if renewed:
        session.expires = now + SESSION_LIFETIME
    if renewed or now - session.last_used >= LAST_USED_RESOLUTION:
        session.last_used = now
        db.add(session)
        await db.commit()
    return FoundSession(session=session, user=user, renewed=renewed)


async def revoke_session(db: AsyncSession, token: str) -> None:
    await db.exec(delete(AuthSession).where(col(AuthSession.token_hash) == hash_secret(token)))
    await db.commit()


def app_origin(settings: Settings) -> str:
    url = urlsplit(settings.app_url)
    return f"{url.scheme}://{url.netloc}"


def is_https(settings: Settings) -> bool:
    return settings.app_url.startswith("https://")


def session_cookie_name(settings: Settings) -> str:
    # The __Host- prefix stops a subdomain from planting or overwriting the cookie; browsers accept it only on a Secure cookie
    return "__Host-yapit_session" if is_https(settings) else "yapit_session"


def set_auth_cookie(response: Response, name: str, value: str, max_age: int, settings: Settings) -> None:
    response.set_cookie(
        name, value, max_age=max_age, path="/", httponly=True, samesite="lax", secure=is_https(settings)
    )


def clear_auth_cookie(response: Response, name: str, settings: Settings) -> None:
    response.delete_cookie(name, path="/", httponly=True, samesite="lax", secure=is_https(settings))


def set_session_cookie(response: Response, token: str, expires: datetime, settings: Settings) -> None:
    max_age = round((expires - datetime.now(tz=dt.UTC)).total_seconds())
    set_auth_cookie(response, session_cookie_name(settings), token, max_age, settings)


def clear_session_cookie(response: Response, settings: Settings) -> None:
    clear_auth_cookie(response, session_cookie_name(settings), settings)
