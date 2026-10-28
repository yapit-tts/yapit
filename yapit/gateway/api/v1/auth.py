from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel, EmailStr, StringConstraints
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import AuthRefused, Credentials, request_credentials, require_app_origin, resolve_caller
from yapit.gateway.auth.email_sign_in import (
    CHALLENGE_LIFETIME,
    EmailTaken,
    OtherBrowser,
    TooManyChallenges,
    start_email_change,
    start_sign_in,
    verify_sign_in_code,
    verify_sign_in_token,
)
from yapit.gateway.auth.mailer import MailDeliveryError, Mailer, get_mailer
from yapit.gateway.auth.oauth import PROVIDERS, disconnect, enabled_providers
from yapit.gateway.auth.sessions import (
    SIGN_IN_PENDING_COOKIE,
    clear_auth_cookie,
    clear_session_cookie,
    create_api_token,
    create_browser_session,
    hash_secret,
    new_secret,
    revoke_session,
    session_cookie_name,
    set_auth_cookie,
    set_session_cookie,
)
from yapit.gateway.config import Settings
from yapit.gateway.deps import DbSession, SettingsDep, SignedInAccount
from yapit.gateway.domain_models import AuthSession, AuthSessionKind, OAuthIdentity, UserAccount
from yapit.gateway.rate_limit import limiter

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class Identity(BaseModel):
    provider: str
    email: str | None


class SessionUser(BaseModel):
    id: str
    email: str
    name: str | None
    identities: list[Identity]


class SessionState(BaseModel):
    auth_enabled: bool
    providers: list[str]  # the OAuth providers sign-in offers
    user: SessionUser | None


class EmailStartRequest(BaseModel):
    email: EmailStr


class VerifyByToken(BaseModel):
    token: str
    same_browser_only: bool = False  # sign in only if this browser asked for the link; else 409, consuming nothing


class VerifyByCode(BaseModel):
    email: EmailStr
    code: str


class ApiToken(BaseModel):
    id: str
    label: str
    created: datetime
    last_used: datetime


class NewApiToken(ApiToken):
    token: str  # shown this once


class CreateApiToken(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


@router.get("/session")
async def get_session(
    response: Response,
    settings: SettingsDep,
    db: DbSession,
    credentials: Annotated[Credentials, Depends(request_credentials)],
) -> SessionState:
    """Who the browser is signed in as; `user` is null for anyone else, wrong credentials included.

    Also refreshes the session cookie, or clears one that opens no session.
    """
    if not settings.auth_enabled:
        return SessionState(auth_enabled=False, providers=[], user=None)
    try:
        caller = await resolve_caller(db, settings, credentials)
    except AuthRefused:
        return SessionState(auth_enabled=True, providers=enabled_providers(settings), user=None)
    if caller.session_expires is not None and credentials.session_token:
        set_session_cookie(response, credentials.session_token, caller.session_expires, settings)
    elif credentials.session_token:
        clear_session_cookie(response, settings)
    if caller.user is None or caller.user.is_anonymous:
        return SessionState(auth_enabled=True, providers=enabled_providers(settings), user=None)
    return await _session_state(db, settings, caller.user.id)


@router.post("/email/start", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def start_email_sign_in(
    request: Request,
    response: Response,
    body: EmailStartRequest,
    settings: SettingsDep,
    db: DbSession,
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> None:
    """Email a sign-in link and code. Signing in with a new address creates its account."""
    _require_auth_enabled(settings)
    # One nonce per browser, so the links of every mail it asked for sign it in without a click
    browser_nonce = request.cookies.get(SIGN_IN_PENDING_COOKIE) or new_secret()
    with _sending_challenge_to(body.email):
        await start_sign_in(db, mailer, settings, body.email, browser_nonce)
    set_auth_cookie(response, SIGN_IN_PENDING_COOKIE, browser_nonce, int(CHALLENGE_LIFETIME.total_seconds()), settings)


@router.post("/email/change", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def change_email(
    request: Request,
    response: Response,
    body: EmailStartRequest,
    user: SignedInAccount,
    settings: SettingsDep,
    db: DbSession,
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> None:
    """Email a link and code to the new address; `/email/verify` with either switches the account to it."""
    browser_nonce = request.cookies.get(SIGN_IN_PENDING_COOKIE) or new_secret()
    with _sending_challenge_to(body.email):
        try:
            await start_email_change(db, mailer, settings, user.id, body.email, browser_nonce)
        except EmailTaken:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account already uses this address.")
    set_auth_cookie(response, SIGN_IN_PENDING_COOKIE, browser_nonce, int(CHALLENGE_LIFETIME.total_seconds()), settings)


@router.post("/email/verify")
@limiter.limit("20/hour")
async def verify_email_sign_in(
    request: Request,
    response: Response,
    body: VerifyByToken | VerifyByCode,
    settings: SettingsDep,
    db: DbSession,
) -> SessionState:
    """Sign in with the link's token or the emailed code, and start a browser session.

    A link or code from an email change switches the account to the new address and signs it in.
    """
    _require_auth_enabled(settings)
    _refuse_other_origins(request, settings)
    try:
        if isinstance(body, VerifyByToken):
            try:
                account = await verify_sign_in_token(
                    db,
                    body.token,
                    browser_nonce=request.cookies.get(SIGN_IN_PENDING_COOKIE),
                    same_browser_only=body.same_browser_only,
                )
            except OtherBrowser:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This browser did not ask for the link; confirm to sign in.",
                )
        else:
            account = await verify_sign_in_code(db, body.email, body.code.strip())
    except EmailTaken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Another account has taken this address since."
        )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This sign-in link or code is invalid, used or expired."
        )

    if previous := request.cookies.get(session_cookie_name(settings)):
        await revoke_session(db, previous)
    token, expires = create_browser_session(db, account.id)
    await db.commit()
    set_session_cookie(response, token, expires, settings)
    clear_auth_cookie(response, SIGN_IN_PENDING_COOKIE, settings)
    logger.info(f"User {account.id} signed in by email")
    return await _session_state(db, settings, account.id)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(request: Request, response: Response, settings: SettingsDep, db: DbSession) -> None:
    _require_auth_enabled(settings)
    if token := request.cookies.get(session_cookie_name(settings)):
        _refuse_other_origins(request, settings)
        await revoke_session(db, token)
    clear_session_cookie(response, settings)


def _refuse_other_origins(request: Request, settings: Settings) -> None:
    try:
        require_app_origin(request.headers.get("origin"), settings)
    except AuthRefused as refused:
        raise HTTPException(status_code=refused.status_code, detail=refused.reason)


def _require_auth_enabled(settings: Settings) -> None:
    if not settings.auth_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sign-in is disabled (AUTH_ENABLED=false).")


@router.delete("/identities/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_identity(provider: str, user: SignedInAccount, db: DbSession) -> None:
    """Stop the user's Google or GitHub account from signing in to it; email sign-in always stays."""
    if provider not in PROVIDERS or not await disconnect(db, user.id, provider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No {provider} account is connected.")


@router.get("/tokens")
async def list_api_tokens(user: SignedInAccount, db: DbSession) -> list[ApiToken]:
    rows = (
        await db.exec(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.kind == AuthSessionKind.api)
            .order_by(col(AuthSession.created))
        )
    ).all()
    return [_api_token(row) for row in rows]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(body: CreateApiToken, user: SignedInAccount, db: DbSession) -> NewApiToken:
    """A new API token for scripts and the CLI. The answer is the only place the token itself appears."""
    token = create_api_token(db, user.id, body.label)
    await db.commit()
    row = await db.get_one(AuthSession, hash_secret(token))
    return NewApiToken(**_api_token(row).model_dump(), token=token)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_token(token_id: str, user: SignedInAccount, db: DbSession) -> None:
    result = await db.exec(
        delete(AuthSession).where(
            col(AuthSession.token_hash) == token_id,
            col(AuthSession.user_id) == user.id,
            col(AuthSession.kind) == AuthSessionKind.api,
        )
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such API token.")


def _api_token(row: AuthSession) -> ApiToken:
    # The stored hash doubles as the id: it names the token but cannot authenticate as it
    assert row.label is not None
    return ApiToken(id=row.token_hash, label=row.label, created=row.created, last_used=row.last_used)


@contextmanager
def _sending_challenge_to(email: str) -> Iterator[None]:
    try:
        yield
    except TooManyChallenges:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many emails to this address. Try again in {CHALLENGE_LIFETIME.seconds // 60} minutes.",
        )
    except MailDeliveryError:
        logger.exception(f"Auth email to an address at {email.rpartition('@')[2]} failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not send the email.")


async def _session_state(db: AsyncSession, settings: Settings, user_id: str) -> SessionState:
    account = await db.get(UserAccount, user_id)
    assert account is not None
    identities = (await db.exec(select(OAuthIdentity).where(OAuthIdentity.user_id == user_id))).all()
    return SessionState(
        auth_enabled=True,
        providers=enabled_providers(settings),
        user=SessionUser(
            id=account.id,
            email=account.email,
            name=account.name,
            identities=[Identity(provider=i.provider, email=i.email) for i in identities],
        ),
    )
