from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel, StringConstraints
from sqlmodel import col, delete

from yapit.gateway.api.v1.auth import SessionState, refuse_other_origins, session_state
from yapit.gateway.auth.passkeys import (
    PasskeyFailed,
    RelyingParty,
    register,
    registration_options,
    relying_party,
    sign_in,
    sign_in_options,
    user_passkeys,
)
from yapit.gateway.auth.sessions import start_browser_session
from yapit.gateway.deps import DbSession, RedisClient, SettingsDep, SignedInAccount
from yapit.gateway.domain_models import Passkey, UserAccount
from yapit.gateway.rate_limit import limiter

router = APIRouter(prefix="/v1/auth/passkeys", tags=["Auth"])

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def available_relying_party(settings: SettingsDep) -> RelyingParty:
    rp = relying_party(settings)
    if rp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passkeys need sign-in enabled and Yapit served over https (or localhost).",
        )
    return rp


AvailableRelyingParty = Annotated[RelyingParty, Depends(available_relying_party)]


class CeremonyOptions(BaseModel):
    flow: str
    options: dict[str, Any]  # for navigator.credentials.create() or .get(), in WebAuthn's JSON form


class NewPasskey(BaseModel):
    flow: str
    credential: dict[str, Any]  # the PublicKeyCredential the browser created, in WebAuthn's JSON form
    label: Label


class PasskeySignIn(BaseModel):
    flow: str
    credential: dict[str, Any]


class RenamePasskey(BaseModel):
    label: Label


class PasskeyInfo(BaseModel):
    id: str
    label: str
    created: datetime
    last_used: datetime | None


@router.get("")
async def list_passkeys(user: SignedInAccount, db: DbSession) -> list[PasskeyInfo]:
    return [_info(p) for p in await user_passkeys(db, user.id)]


@router.post("/register/options")
async def start_registration(
    user: SignedInAccount, rp: AvailableRelyingParty, db: DbSession, redis: RedisClient
) -> CeremonyOptions:
    flow, options = await registration_options(db, redis, rp, await db.get_one(UserAccount, user.id))
    return CeremonyOptions(flow=flow, options=options)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_passkey(
    body: NewPasskey, user: SignedInAccount, rp: AvailableRelyingParty, db: DbSession, redis: RedisClient
) -> PasskeyInfo:
    try:
        passkey = await register(db, redis, rp, user.id, body.flow, body.credential, body.label)
    except PasskeyFailed as failed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=failed.reason)
    logger.info(f"User {user.id} added a passkey")
    return _info(passkey)


@router.patch("/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def rename_passkey(passkey_id: str, body: RenamePasskey, user: SignedInAccount, db: DbSession) -> None:
    passkey = await db.get(Passkey, passkey_id)
    if passkey is None or passkey.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such passkey.")
    passkey.label = body.label
    db.add(passkey)
    await db.commit()


@router.delete("/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_passkey(passkey_id: str, user: SignedInAccount, db: DbSession) -> None:
    """Stop the passkey from signing in. The authenticator keeps its copy until it is deleted there too."""
    result = await db.exec(
        delete(Passkey).where(col(Passkey.credential_id) == passkey_id, col(Passkey.user_id) == user.id)
    )
    await db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such passkey.")


@router.post("/sign-in/options")
@limiter.limit("30/hour")
async def start_sign_in(request: Request, rp: AvailableRelyingParty, redis: RedisClient) -> CeremonyOptions:
    flow, options = await sign_in_options(redis, rp)
    return CeremonyOptions(flow=flow, options=options)


@router.post("/sign-in")
@limiter.limit("30/hour")
async def sign_in_with_passkey(
    request: Request,
    response: Response,
    body: PasskeySignIn,
    rp: AvailableRelyingParty,
    settings: SettingsDep,
    db: DbSession,
    redis: RedisClient,
) -> SessionState:
    """Sign in with a passkey and start a browser session."""
    refuse_other_origins(request, settings)
    try:
        account = await sign_in(db, redis, rp, body.flow, body.credential)
    except PasskeyFailed as failed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=failed.reason)
    await start_browser_session(db, request, response, settings, account.id)
    logger.info(f"User {account.id} signed in with a passkey")
    return await session_state(db, settings, account.id)


def _info(passkey: Passkey) -> PasskeyInfo:
    return PasskeyInfo(
        id=passkey.credential_id, label=passkey.label, created=passkey.created, last_used=passkey.last_used
    )
