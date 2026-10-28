from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel, EmailStr
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import AuthRefused, Credentials, request_credentials, require_app_origin, resolve_caller
from yapit.gateway.auth.email_sign_in import (
    CHALLENGE_LIFETIME,
    OtherBrowser,
    TooManyChallenges,
    start_sign_in,
    verify_sign_in_code,
    verify_sign_in_token,
)
from yapit.gateway.auth.mailer import MailDeliveryError, Mailer, get_mailer
from yapit.gateway.auth.sessions import (
    SIGN_IN_PENDING_COOKIE,
    clear_auth_cookie,
    clear_session_cookie,
    create_browser_session,
    new_secret,
    revoke_session,
    session_cookie_name,
    set_auth_cookie,
    set_session_cookie,
)
from yapit.gateway.config import Settings
from yapit.gateway.deps import DbSession, SettingsDep
from yapit.gateway.domain_models import OAuthIdentity, UserAccount
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
    user: SessionUser | None


class EmailStartRequest(BaseModel):
    email: EmailStr


class VerifyByToken(BaseModel):
    token: str
    same_browser_only: bool = False  # sign in only if this browser asked for the link; else 409, consuming nothing


class VerifyByCode(BaseModel):
    email: EmailStr
    code: str


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
        return SessionState(auth_enabled=False, user=None)
    try:
        caller = await resolve_caller(db, settings, credentials)
    except AuthRefused:
        return SessionState(auth_enabled=True, user=None)
    if caller.session_expires is not None and credentials.session_token:
        set_session_cookie(response, credentials.session_token, caller.session_expires, settings)
    elif credentials.session_token:
        clear_session_cookie(response, settings)
    if caller.user is None or caller.user.is_anonymous:
        return SessionState(auth_enabled=True, user=None)
    return await _session_state(db, caller.user.id)


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
    try:
        await start_sign_in(db, mailer, settings, body.email, browser_nonce)
    except TooManyChallenges:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many sign-in emails to this address. Try again in {CHALLENGE_LIFETIME.seconds // 60} minutes.",
        )
    except MailDeliveryError:
        logger.exception(f"Sign-in email to an address at {body.email.rpartition('@')[2]} failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not send the sign-in email.")
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
    """Sign in with the link's token or the emailed code, and start a browser session."""
    _require_auth_enabled(settings)
    _refuse_other_origins(request, settings)
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
    return await _session_state(db, account.id)


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


async def _session_state(db: AsyncSession, user_id: str) -> SessionState:
    account = await db.get(UserAccount, user_id)
    assert account is not None
    identities = (await db.exec(select(OAuthIdentity).where(OAuthIdentity.user_id == user_id))).all()
    return SessionState(
        auth_enabled=True,
        user=SessionUser(
            id=account.id,
            email=account.email,
            name=account.name,
            identities=[Identity(provider=i.provider, email=i.email) for i in identities],
        ),
    )
