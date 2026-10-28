from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel, EmailStr
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth import Caller, identify_caller, require_app_origin
from yapit.gateway.auth.email_sign_in import (
    TooManyChallenges,
    start_sign_in,
    verify_sign_in_code,
    verify_sign_in_token,
)
from yapit.gateway.auth.mailer import MailDeliveryError, Mailer, get_mailer
from yapit.gateway.auth.sessions import (
    SESSION_COOKIE,
    clear_session_cookie,
    create_browser_session,
    revoke_session,
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


class VerifyByCode(BaseModel):
    email: EmailStr
    code: str


@router.get("/session")
async def get_session(
    request: Request,
    response: Response,
    settings: SettingsDep,
    db: DbSession,
    caller: Annotated[Caller, Depends(identify_caller)],
) -> SessionState:
    """Who the browser is signed in as. Also refreshes the session cookie, or clears one that opens no session."""
    if not settings.auth_enabled:
        return SessionState(auth_enabled=False, user=None)
    if caller.browser_session is not None and caller.browser_session.expires is not None:
        set_session_cookie(response, request.cookies[SESSION_COOKIE], caller.browser_session.expires, settings)
    elif SESSION_COOKIE in request.cookies:
        clear_session_cookie(response, settings)
    if caller.user is None or caller.user.is_anonymous:
        return SessionState(auth_enabled=True, user=None)
    return await _session_state(db, caller.user.id)


@router.post("/email/start", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def start_email_sign_in(
    request: Request,
    body: EmailStartRequest,
    settings: SettingsDep,
    db: DbSession,
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> None:
    """Email a sign-in link and code. Signing in with a new address creates its account."""
    _require_auth_enabled(settings)
    try:
        await start_sign_in(db, mailer, settings, body.email)
    except TooManyChallenges:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in emails to this address. Try again in 15 minutes.",
        )
    except MailDeliveryError:
        logger.exception(f"Sign-in email to an address at {body.email.rpartition('@')[2]} failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not send the sign-in email.")


@router.post("/email/verify")
async def verify_email_sign_in(
    request: Request,
    response: Response,
    body: VerifyByToken | VerifyByCode,
    settings: SettingsDep,
    db: DbSession,
) -> SessionState:
    """Sign in with the link's token or the emailed code, and start a browser session."""
    _require_auth_enabled(settings)
    require_app_origin(request, settings)
    if isinstance(body, VerifyByToken):
        account = await verify_sign_in_token(db, body.token)
    else:
        account = await verify_sign_in_code(db, body.email, body.code.strip())
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This sign-in link or code is invalid, used or expired."
        )

    if previous := request.cookies.get(SESSION_COOKIE):
        await revoke_session(db, previous)
    token, session = create_browser_session(db, account.id)
    await db.commit()
    assert session.expires is not None
    set_session_cookie(response, token, session.expires, settings)
    logger.info(f"User {account.id} signed in by email")
    return await _session_state(db, account.id)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(request: Request, response: Response, settings: SettingsDep, db: DbSession) -> None:
    _require_auth_enabled(settings)
    if token := request.cookies.get(SESSION_COOKIE):
        require_app_origin(request, settings)
        await revoke_session(db, token)
    clear_session_cookie(response, settings)


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
