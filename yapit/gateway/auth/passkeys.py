"""Passkey sign-in (WebAuthn): adding a passkey to a signed-in account, and signing in with one.

A ceremony is two requests: the options carry a fresh challenge, kept in Redis under a random
flow id for one use; the browser's answer comes back with that flow id and is verified against it.
Passkeys are discoverable and always ask for user verification (a PIN, fingerprint or face),
so a passkey alone signs in, and no email is typed.
"""

import datetime as dt
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum, auto
from typing import Any
from urllib.parse import urlsplit

from redis.asyncio import Redis
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from yapit.gateway.auth.sessions import app_origin
from yapit.gateway.config import Settings
from yapit.gateway.domain_models import Passkey, UserAccount

RP_NAME = "Yapit"
CEREMONY_LIFETIME = timedelta(minutes=5)


class PasskeyFailed(Exception):
    def __init__(self, reason: str):
        self.reason = reason


@dataclass(frozen=True)
class RelyingParty:
    id: str  # the host passkeys are bound to
    origin: str


def relying_party(settings: Settings) -> RelyingParty | None:
    """Whom passkeys belong to, or None where browsers refuse WebAuthn: sign-in off, or plain http off localhost."""
    if not settings.auth_enabled:
        return None
    url = urlsplit(settings.app_url)
    if url.hostname is None or (url.scheme != "https" and url.hostname != "localhost"):
        return None
    return RelyingParty(id=url.hostname, origin=app_origin(settings))


class CeremonyPurpose(StrEnum):
    register = auto()
    sign_in = auto()


@dataclass(frozen=True)
class Ceremony:
    purpose: CeremonyPurpose
    challenge: str  # base64url
    user_id: str | None  # register: the account the passkey is added to


def _ceremony_key(flow: str) -> str:
    return f"passkey_ceremony:{flow}"


async def _remember(redis: Redis, ceremony: Ceremony) -> str:
    flow = secrets.token_urlsafe(32)
    await redis.set(_ceremony_key(flow), json.dumps(asdict(ceremony)), ex=int(CEREMONY_LIFETIME.total_seconds()))
    return flow


async def _take(redis: Redis, flow: str, purpose: CeremonyPurpose) -> Ceremony:
    raw = await redis.getdel(_ceremony_key(flow))  # ty: ignore[unresolved-attribute] - present at runtime, missing from the stubs
    if raw is None:
        raise PasskeyFailed("That took too long. Please try again.")
    stored = json.loads(raw)
    ceremony = Ceremony(**stored | {"purpose": CeremonyPurpose(stored["purpose"])})
    if ceremony.purpose != purpose:
        raise PasskeyFailed("That took too long. Please try again.")
    return ceremony


def _descriptor(passkey: Passkey) -> PublicKeyCredentialDescriptor:
    transports = [
        AuthenticatorTransport(t) for t in passkey.transports if t in AuthenticatorTransport._value2member_map_
    ]
    return PublicKeyCredentialDescriptor(id=base64url_to_bytes(passkey.credential_id), transports=transports or None)


async def user_passkeys(db: AsyncSession, user_id: str) -> list[Passkey]:
    return list((await db.exec(select(Passkey).where(Passkey.user_id == user_id).order_by(col(Passkey.created)))).all())


async def registration_options(
    db: AsyncSession, redis: Redis, rp: RelyingParty, account: UserAccount
) -> tuple[str, dict[str, Any]]:
    """The flow id and the options for `navigator.credentials.create()` that add a passkey to this account."""
    options = generate_registration_options(
        rp_id=rp.id,
        rp_name=RP_NAME,
        user_name=account.email,
        # The authenticator keeps one passkey per site and user id, so a stable id replaces rather than piles up
        user_id=account.id.encode(),
        user_display_name=account.name or account.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[_descriptor(p) for p in await user_passkeys(db, account.id)],
    )
    challenge = bytes_to_base64url(options.challenge)
    flow = await _remember(redis, Ceremony(CeremonyPurpose.register, challenge, account.id))
    return flow, options_to_json_dict(options)


async def register(
    db: AsyncSession, redis: Redis, rp: RelyingParty, user_id: str, flow: str, credential: dict[str, Any], label: str
) -> Passkey:
    """Verify the browser's answer to the registration options and store the passkey. Commits."""
    ceremony = await _take(redis, flow, CeremonyPurpose.register)
    if ceremony.user_id != user_id:
        raise PasskeyFailed("That took too long. Please try again.")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(ceremony.challenge),
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
    except InvalidRegistrationResponse as e:
        raise PasskeyFailed(f"The passkey could not be verified: {e}")

    credential_id = bytes_to_base64url(verified.credential_id)
    if await db.get(Passkey, credential_id) is not None:
        raise PasskeyFailed("This passkey is already added.")
    response = credential.get("response")
    transports = response.get("transports") if isinstance(response, dict) else None
    passkey = Passkey(
        credential_id=credential_id,
        user_id=user_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=[t for t in transports or [] if isinstance(t, str)],
        label=label,
    )
    db.add(passkey)
    await db.commit()
    await db.refresh(passkey)
    return passkey


async def sign_in_options(redis: Redis, rp: RelyingParty) -> tuple[str, dict[str, Any]]:
    """The flow id and the options for `navigator.credentials.get()`. No credentials are listed,
    so the browser offers every passkey it holds for the site.
    """
    options = generate_authentication_options(rp_id=rp.id, user_verification=UserVerificationRequirement.REQUIRED)
    flow = await _remember(redis, Ceremony(CeremonyPurpose.sign_in, bytes_to_base64url(options.challenge), None))
    return flow, options_to_json_dict(options)


def _is_user_handle_of(user_handle: object, user_id: str) -> bool:
    try:
        return isinstance(user_handle, str) and base64url_to_bytes(user_handle) == user_id.encode()
    except ValueError:
        return False


async def sign_in(
    db: AsyncSession, redis: Redis, rp: RelyingParty, flow: str, credential: dict[str, Any]
) -> UserAccount:
    """The account the browser's answer to the sign-in options signs in to. Commits."""
    ceremony = await _take(redis, flow, CeremonyPurpose.sign_in)
    credential_id = credential.get("id")
    passkey = await db.get(Passkey, credential_id) if isinstance(credential_id, str) else None
    if passkey is None:
        raise PasskeyFailed("Yapit does not know this passkey. Sign in another way and add it on the account page.")

    response = credential.get("response")
    user_handle = response.get("userHandle") if isinstance(response, dict) else None
    if user_handle is not None and not _is_user_handle_of(user_handle, passkey.user_id):
        raise PasskeyFailed("The passkey could not be verified.")
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(ceremony.challenge),
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except InvalidAuthenticationResponse as e:
        raise PasskeyFailed(f"The passkey could not be verified: {e}")

    now = datetime.now(tz=dt.UTC)
    passkey.sign_count = verified.new_sign_count
    passkey.last_used = now
    account = await db.get_one(UserAccount, passkey.user_id)
    account.last_sign_in = now
    db.add_all([passkey, account])
    await db.commit()
    return account
