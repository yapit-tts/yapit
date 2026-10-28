import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, Security, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.sessions import app_origin, find_session, session_cookie_name, set_session_cookie
from yapit.gateway.config import Settings, get_settings
from yapit.gateway.db import create_session, get_db_session
from yapit.gateway.domain_models import AuthSessionKind, UserAccount

bearer = HTTPBearer(auto_error=False)

ANONYMOUS_ID_PREFIX = "anon-"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class User(BaseModel):
    id: str
    is_anonymous: bool
    email: str | None = None


SELFHOST_USER = User(id="selfhost", is_anonymous=False)


@dataclass
class Credentials:
    """What a request or WebSocket handshake carries that could say who sent it."""

    bearer_token: str | None
    session_token: str | None
    origin: str | None
    changes_state: bool  # an unsafe HTTP method, or a WebSocket handshake
    anonymous_id: str | None
    anonymous_token: str | None


@dataclass
class Caller:
    user: User | None
    session_expires: datetime | None = None  # set when the session cookie authenticated the request
    session_renewed: bool = False


class AuthRefused(Exception):
    def __init__(self, status_code: int, reason: str):
        self.status_code = status_code
        self.reason = reason


def sign_anonymous_id(anonymous_id: str, secret: str) -> str:
    return hmac.new(secret.encode(), anonymous_id.encode(), hashlib.sha256).hexdigest()


def verify_anonymous_token(anonymous_id: str, token: str, secret: str) -> bool:
    return hmac.compare_digest(sign_anonymous_id(anonymous_id, secret), token)


def create_anonymous_user(anonymous_id: str) -> User:
    return User(id=f"{ANONYMOUS_ID_PREFIX}{anonymous_id}", is_anonymous=True)


def account_user(account: UserAccount) -> User:
    return User(id=account.id, is_anonymous=False, email=account.email)


def require_app_origin(origin: str | None, settings: Settings) -> None:
    """Refuse a cookie-authenticated state change sent from another site (CSRF)."""
    if origin != app_origin(settings):
        raise AuthRefused(status.HTTP_403_FORBIDDEN, "cross-origin request refused")


async def resolve_caller(db: AsyncSession, settings: Settings, credentials: Credentials) -> Caller:
    """Who sent the request: a bearer API token wins over the session cookie, which wins over an anonymous session.

    A session cookie that opens no live session is ignored, so a browser holding a stale
    cookie can still act anonymously. Raises AuthRefused for credentials that are present but wrong.
    """
    if not settings.auth_enabled:
        return Caller(SELFHOST_USER)

    if credentials.bearer_token is not None:
        found = await find_session(db, credentials.bearer_token, AuthSessionKind.api)
        if found is None:
            raise AuthRefused(status.HTTP_401_UNAUTHORIZED, "invalid API token")
        return Caller(account_user(found.user))

    if credentials.session_token and (
        found := await find_session(db, credentials.session_token, AuthSessionKind.browser)
    ):
        if credentials.changes_state:
            require_app_origin(credentials.origin, settings)
        return Caller(account_user(found.user), session_expires=found.session.expires, session_renewed=found.renewed)

    if credentials.anonymous_id is not None:
        if not credentials.anonymous_token or not verify_anonymous_token(
            credentials.anonymous_id, credentials.anonymous_token, settings.anonymous_session_secret
        ):
            raise AuthRefused(status.HTTP_401_UNAUTHORIZED, "invalid anonymous session")
        return Caller(create_anonymous_user(credentials.anonymous_id))

    return Caller(None)


def request_credentials(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
    x_anonymous_id: str | None = Header(None, alias="X-Anonymous-ID"),
    x_anonymous_token: str | None = Header(None, alias="X-Anonymous-Token"),
) -> Credentials:
    return Credentials(
        bearer_token=creds.credentials if creds is not None else None,
        session_token=request.cookies.get(session_cookie_name(settings)),
        origin=request.headers.get("origin"),
        changes_state=request.method not in SAFE_METHODS,
        anonymous_id=x_anonymous_id,
        anonymous_token=x_anonymous_token,
    )


async def identify_caller(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    credentials: Annotated[Credentials, Depends(request_credentials)],
) -> Caller:
    try:
        caller = await resolve_caller(db, settings, credentials)
    except AuthRefused as refused:
        raise HTTPException(
            status_code=refused.status_code,
            detail=refused.reason,
            headers={"WWW-Authenticate": "Bearer"} if refused.status_code == status.HTTP_401_UNAUTHORIZED else None,
        )
    if caller.session_renewed and caller.session_expires is not None and credentials.session_token:
        set_session_cookie(response, credentials.session_token, caller.session_expires, settings)
    return caller


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


async def authenticate_account(
    user: Annotated[User, Depends(authenticate)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """The caller, who must be signed in to an account: not anonymous, and not the selfhost user without auth."""
    if not settings.auth_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sign-in is disabled (AUTH_ENABLED=false).")
    if user.is_anonymous:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in first.")
    return user


async def authenticate_ws(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """The WebSocket's caller: a bearer API token, the session cookie, or an anonymous session in the query."""
    scheme, _, token = (websocket.headers.get("authorization") or "").partition(" ")
    credentials = Credentials(
        bearer_token=token if scheme.lower() == "bearer" else None,
        session_token=websocket.cookies.get(session_cookie_name(settings)),
        origin=websocket.headers.get("origin"),
        changes_state=True,
        anonymous_id=websocket.query_params.get("anonymous_id"),
        anonymous_token=websocket.query_params.get("anonymous_token"),
    )
    try:
        async with create_session() as db:
            caller = await resolve_caller(db, settings, credentials)
    except AuthRefused as refused:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=refused.reason)
    if caller.user is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated")
    return caller.user
