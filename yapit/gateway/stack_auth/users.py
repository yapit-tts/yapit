import asyncio
import time
from typing import Any

import httpx
import jwt
from loguru import logger
from pydantic import BaseModel, Field

from yapit.gateway.config import Settings
from yapit.gateway.stack_auth.api import build_headers

SIGNING_KEYS_REFETCH_SECONDS = 60

_client: httpx.AsyncClient | None = None
_signing_keys: dict[str, jwt.PyJWK] = {}
_signing_keys_fetched_at = float("-inf")
_signing_keys_lock = asyncio.Lock()


def init_stack_auth_client(base_url: str) -> None:
    global _client
    _client = httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(10, connect=3),
    )


async def close_stack_auth_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _request(method: str, url: str, headers: dict[str, Any]) -> httpx.Response:
    """Make an HTTP request with a single retry on transient network errors."""
    assert _client is not None, "Call init_stack_auth_client() during app startup"
    last_exc: Exception = Exception("unreachable")
    for attempt in range(2):
        try:
            return await _client.request(method, url, headers=headers)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning(f"Stack Auth {type(exc).__name__}, retrying")
                await asyncio.sleep(0.5)
    raise last_exc


class User(BaseModel):
    id: str
    is_anonymous: bool
    primary_email: str | None = Field(default=None)


async def _signing_key(settings: Settings, kid: str) -> jwt.PyJWK | None:
    """The project's public key with this id, fetching the key set when the id is new.

    An unknown id refetches at most once per SIGNING_KEYS_REFETCH_SECONDS, so tokens
    with made-up key ids cannot turn every request into a request to Stack Auth.
    """
    global _signing_keys, _signing_keys_fetched_at
    if kid in _signing_keys:
        return _signing_keys[kid]
    async with _signing_keys_lock:
        if kid not in _signing_keys and time.monotonic() - _signing_keys_fetched_at >= SIGNING_KEYS_REFETCH_SECONDS:
            response = await _request(
                "GET", f"/api/v1/projects/{settings.stack_auth_project_id}/.well-known/jwks.json", {}
            )
            response.raise_for_status()
            _signing_keys = {key["kid"]: jwt.PyJWK(key) for key in response.json()["keys"]}
            _signing_keys_fetched_at = time.monotonic()
    return _signing_keys.get(kid)


async def verify_access_token(settings: Settings, access_token: str) -> User | None:
    """The signed-up user a Stack Auth access token belongs to, or None if the token is invalid or expired.

    Stack Auth signs the tokens of its anonymous and restricted users with keys of their
    own, which the project's key set leaves out, so those tokens fail here.
    """
    assert settings.stack_auth_project_id, "STACK_AUTH_PROJECT_ID is required when auth is enabled"
    try:
        kid = jwt.get_unverified_header(access_token).get("kid")
    except jwt.InvalidTokenError:
        return None
    if not isinstance(kid, str):
        return None
    key = await _signing_key(settings, kid)
    if key is None:
        return None
    try:
        claims = jwt.decode(
            access_token,
            key,
            algorithms=["ES256"],
            audience=settings.stack_auth_project_id,
            options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.InvalidTokenError:
        return None
    return User(id=claims["sub"], is_anonymous=False, primary_email=claims.get("email"))


async def delete_user(settings: Settings, access_token: str, user_id: str) -> bool:
    """Delete a user from Stack Auth. Returns True if successful."""
    headers = build_headers(settings, access_token=access_token)
    response = await _request("DELETE", f"/api/v1/users/{user_id}", headers)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True
