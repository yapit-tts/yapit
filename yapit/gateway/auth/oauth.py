"""Google and GitHub sign-in: the authorization code flow with PKCE, and which account an identity signs in to."""

import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum, auto
from urllib.parse import urlencode, urlsplit

import httpx
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.accounts import normalize_email, sign_in_by_email
from yapit.gateway.auth.sessions import app_origin
from yapit.gateway.config import Settings
from yapit.gateway.domain_models import OAuthIdentity, UserAccount

OAUTH_STATE_COOKIE = "yapit_oauth_state"
STATE_LIFETIME = timedelta(minutes=10)
PROVIDER_TIMEOUT_S = 10


class OAuthMode(StrEnum):
    sign_in = auto()
    link = auto()  # from account settings: attach the identity to the signed-in user


class OAuthError(StrEnum):
    """The codes the callback redirects with, as `?error=<code>`; the frontend words each one."""

    state = auto()  # unknown, expired or used state, or another browser's
    issuer = auto()  # the callback's `iss` is not the provider's (RFC 9207)
    denied = auto()  # the person cancelled at the provider
    provider = auto()  # the provider failed or answered something unusable
    email_unverified = auto()  # the provider does not vouch for the email, so it signs in to nothing (P5)
    identity_taken = auto()  # link mode: the identity already signs in to another user
    not_signed_in = auto()  # link mode without, or no longer with, the user who started it


class OAuthFailed(Exception):
    def __init__(self, error: OAuthError, pending: "PendingOAuth | None" = None):
        self.error = error
        self.pending = pending


@dataclass(frozen=True)
class Profile:
    account_id: str
    email: str | None
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class Provider:
    name: str
    issuer: str
    authorize_url: str
    token_url: str
    scope: str
    fetch_profile: Callable[[httpx.AsyncClient, str], Awaitable[Profile]]
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


async def google_profile(http: httpx.AsyncClient, access_token: str) -> Profile:
    info = (
        (
            await http.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        )
        .raise_for_status()
        .json()
    )
    return Profile(
        account_id=info["sub"],
        email=info.get("email"),
        email_verified=info.get("email_verified") is True,
        name=info.get("name"),
    )


async def github_profile(http: httpx.AsyncClient, access_token: str) -> Profile:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
    user = (await http.get("https://api.github.com/user", headers=headers)).raise_for_status().json()
    emails = (await http.get("https://api.github.com/user/emails", headers=headers)).raise_for_status().json()
    primary = next((entry for entry in emails if entry.get("primary")), None)
    return Profile(
        account_id=str(user["id"]),
        email=primary["email"] if primary else None,
        email_verified=primary is not None and primary.get("verified") is True,
        name=user.get("name") or user.get("login"),
    )


PROVIDERS = {
    "google": Provider(
        name="google",
        issuer="https://accounts.google.com",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile",
        fetch_profile=google_profile,
        extra_authorize_params={"prompt": "select_account"},
    ),
    "github": Provider(
        name="github",
        issuer="https://github.com/login/oauth",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scope="read:user user:email",
        fetch_profile=github_profile,
    ),
}


def client_credentials(settings: Settings, provider: str) -> tuple[str, str]:
    return {
        "google": (settings.google_client_id, settings.google_client_secret),
        "github": (settings.github_client_id, settings.github_client_secret),
    }[provider]


def enabled_providers(settings: Settings) -> list[str]:
    return [name for name in PROVIDERS if client_credentials(settings, name)[0]]


def redirect_uri(settings: Settings, provider: str) -> str:
    return f"{app_origin(settings)}/api/v1/auth/oauth/{provider}/callback"


def is_same_origin_path(value: str) -> bool:
    """Whether a redirect to this value stays on the app: an absolute path, not `//host` or a URL."""
    url = urlsplit(value)
    return (
        value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not url.scheme
        and not url.netloc
        and value.isprintable()
    )


@dataclass(frozen=True)
class PendingOAuth:
    """What `start` remembers in Redis until the callback, under the state's value."""

    provider: str
    code_verifier: str
    mode: OAuthMode
    return_to: str
    user_id: str | None  # link mode: the user the identity attaches to


def _state_key(state: str) -> str:
    return f"oauth_state:{state}"


async def begin(
    redis: Redis, settings: Settings, provider: Provider, mode: OAuthMode, return_to: str, user_id: str | None
) -> tuple[str, str]:
    """Remember a new flow and return the provider URL to send the browser to, and the state to bind it with."""
    state = secrets.token_urlsafe(32)
    pending = PendingOAuth(
        provider=provider.name,
        code_verifier=secrets.token_urlsafe(64),
        mode=mode,
        return_to=return_to,
        user_id=user_id,
    )
    await redis.set(_state_key(state), json.dumps(asdict(pending)), ex=int(STATE_LIFETIME.total_seconds()))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(pending.code_verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client_credentials(settings, provider.name)[0],
        "redirect_uri": redirect_uri(settings, provider.name),
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **provider.extra_authorize_params,
    }
    return f"{provider.authorize_url}?{urlencode(params)}", state


async def take_pending(redis: Redis, provider: Provider, state: str | None, bound_state: str | None) -> PendingOAuth:
    """The flow this callback ends, usable once, and only in the browser that started it."""
    if not state:
        raise OAuthFailed(OAuthError.state)
    raw = await redis.getdel(_state_key(state))  # ty: ignore[unresolved-attribute] - present at runtime, missing from the stubs
    if raw is None:
        raise OAuthFailed(OAuthError.state)
    stored = json.loads(raw)
    pending = PendingOAuth(**stored | {"mode": OAuthMode(stored["mode"])})
    if bound_state is None or not hmac.compare_digest(bound_state, state) or pending.provider != provider.name:
        raise OAuthFailed(OAuthError.state, pending)
    return pending


async def fetch_profile(
    http: httpx.AsyncClient, settings: Settings, provider: Provider, pending: PendingOAuth, params: dict[str, str]
) -> Profile:
    """Check the callback's parameters, trade its code for an access token, and read who signed in at the provider."""
    if "iss" in params and params["iss"] != provider.issuer:
        raise OAuthFailed(OAuthError.issuer, pending)
    if "error" in params:
        raise OAuthFailed(OAuthError.denied if params["error"] == "access_denied" else OAuthError.provider, pending)
    if not params.get("code"):
        raise OAuthFailed(OAuthError.provider, pending)

    client_id, client_secret = client_credentials(settings, provider.name)
    try:
        response = await http.post(
            provider.token_url,
            data={
                "grant_type": "authorization_code",
                "code": params["code"],
                "redirect_uri": redirect_uri(settings, provider.name),
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": pending.code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        # GitHub answers a refused exchange with 200 and an `error` field
        access_token = response.raise_for_status().json().get("access_token")
        if not access_token:
            raise ValueError(f"no access token in the answer: {response.json().get('error')}")
        return await provider.fetch_profile(http, access_token)
    except (httpx.HTTPError, ValueError, KeyError) as e:
        logger.warning(f"OAuth with {provider.name} failed at the provider: {e!r}")
        raise OAuthFailed(OAuthError.provider, pending)


async def resolve_account(
    db: AsyncSession, provider: Provider, profile: Profile, pending: PendingOAuth, current_user_id: str | None
) -> UserAccount:
    """The account this identity signs in to, attaching it where it is new. Commits.

    Sign-in mode: a known identity signs in its user; else a provider-verified email signs in the
    account holding it, created if none does (P5); an unverified email signs in to nothing.
    Link mode: the identity attaches to the user who started the flow, unless it belongs to another.
    """
    now = datetime.now(tz=dt.UTC)
    email = normalize_email(profile.email) if profile.email else None
    identity = await db.get(OAuthIdentity, (provider.name, profile.account_id))

    if pending.mode == OAuthMode.link:
        if pending.user_id is None or current_user_id != pending.user_id:
            raise OAuthFailed(OAuthError.not_signed_in, pending)
        if identity is not None and identity.user_id != pending.user_id:
            raise OAuthFailed(OAuthError.identity_taken, pending)
        account = await db.get_one(UserAccount, pending.user_id)
    elif identity is not None:
        account = await db.get_one(UserAccount, identity.user_id)
        account.last_sign_in = now
        db.add(account)
    elif email is not None and profile.email_verified:
        account = await sign_in_by_email(db, email, now, name=profile.name)
    else:
        raise OAuthFailed(OAuthError.email_unverified, pending)

    await db.exec(
        insert(OAuthIdentity)
        .values(
            provider=provider.name, provider_account_id=profile.account_id, user_id=account.id, email=email, created=now
        )
        .on_conflict_do_update(index_elements=["provider", "provider_account_id"], set_={"email": email})
    )
    await db.commit()
    return account


async def disconnect(db: AsyncSession, user_id: str, provider: str) -> bool:
    """Remove the user's identities at this provider; whether there were any."""
    result = await db.exec(
        delete(OAuthIdentity).where(col(OAuthIdentity.user_id) == user_id, col(OAuthIdentity.provider) == provider)
    )
    await db.commit()
    return bool(result.rowcount)


async def provider_http() -> AsyncIterator[httpx.AsyncClient]:
    """The HTTP client that talks to the providers; tests swap in a stub provider through it."""
    async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT_S) as client:
        yield client
