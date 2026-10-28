import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, Security, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.sessions import SESSION_COOKIE, app_origin, find_session, set_session_cookie
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session, get_db_session
from yapit.gateway.domain_models import AuthSession, AuthSessionKind, UserAccount

bearer = HTTPBearer(auto_error=False)

ANONYMOUS_ID_PREFIX = "anon-"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class User(BaseModel):
    id: str
    is_anonymous: bool
    email: str | None = None


SELFHOST_USER = User(id="selfhost", is_anonymous=False)


@dataclass
class Caller:
    user: User | None
    browser_session: AuthSession | None = None  # set when the session cookie authenticated the request


def verify_anonymous_token(anonymous_id: str, token: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), anonymous_id.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, token)


def create_anonymous_user(anonymous_id: str) -> User:
    return User(id=f"{ANONYMOUS_ID_PREFIX}{anonymous_id}", is_anonymous=True)


def account_user(account: UserAccount) -> User:
    return User(id=account.id, is_anonymous=False, email=account.email)


def require_app_origin(request: Request, settings: Settings) -> None:
    """Refuse a cookie-authenticated state change sent from another site (CSRF)."""
    if request.method not in SAFE_METHODS and request.headers.get("origin") != app_origin(settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cross-origin request refused")


async def identify_caller(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
    x_anonymous_id: str | None = Header(None, alias="X-Anonymous-ID"),
    x_anonymous_token: str | None = Header(None, alias="X-Anonymous-Token"),
) -> Caller:
    """Who sent the request: a bearer API token wins over the session cookie, which wins over an anonymous session.

    A session cookie that opens no live session is ignored, so a browser holding a stale
    cookie can still act anonymously.
    """
    if not settings.auth_enabled:
        return Caller(SELFHOST_USER)

    if creds is not None:
        found = await find_session(db, creds.credentials, AuthSessionKind.api)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Caller(account_user(found.user))

    session_token = request.cookies.get(SESSION_COOKIE)
    if session_token and (found := await find_session(db, session_token, AuthSessionKind.browser)):
        require_app_origin(request, settings)
        if found.renewed:
            assert found.session.expires is not None
            set_session_cookie(response, session_token, found.session.expires, settings)
        return Caller(account_user(found.user), browser_session=found.session)

    if x_anonymous_id is not None:
        if not x_anonymous_token or not verify_anonymous_token(
            x_anonymous_id, x_anonymous_token, settings.anonymous_session_secret
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid anonymous session")
        return Caller(create_anonymous_user(x_anonymous_id))

    return Caller(None)


async def authenticate_optional(caller: Annotated[Caller, Depends(identify_caller)]) -> User | None:
    """The caller, or None when the request carries no credentials (public and shared documents)."""
    return caller.user


async def authenticate(user: Annotated[User | None, Depends(authenticate_optional)]) -> User:
    if user is None:
        logger.debug("no credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def authenticate_ws(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """The WebSocket's caller: a bearer API token, the session cookie, or an anonymous session in the query."""
    if not settings.auth_enabled:
        return SELFHOST_USER

    authorization = websocket.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        async with create_session() as db:
            found = await find_session(db, token, AuthSessionKind.api) if scheme.lower() == "bearer" else None
        if found is None:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API token")
        return account_user(found.user)

    session_token = websocket.cookies.get(SESSION_COOKIE)
    if session_token:
        if websocket.headers.get("origin") != app_origin(settings):
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Cross-origin connection refused")
        async with create_session() as db:
            found = await find_session(db, session_token, AuthSessionKind.browser)
        if found is not None:
            return account_user(found.user)

    anonymous_id = websocket.query_params.get("anonymous_id")
    anonymous_token = websocket.query_params.get("anonymous_token")
    if anonymous_id:
        if not anonymous_token or not verify_anonymous_token(
            anonymous_id, anonymous_token, settings.anonymous_session_secret
        ):
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid anonymous session")
        return create_anonymous_user(anonymous_id)

    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated")
