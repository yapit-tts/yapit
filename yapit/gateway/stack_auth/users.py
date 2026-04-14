import asyncio
from typing import Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from yapit.gateway.config import Settings
from yapit.gateway.stack_auth.api import build_headers

_client: httpx.AsyncClient | None = None


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


# visible to the client
# editable by the client
class UserClientMetadata(BaseModel): ...


# visible to the client
# editable by the server
class UserClientReadOnlyMetadata(BaseModel):
    tier: Literal["free", "pro"] | None = Field(default=None)


# visible to the server
# editable by the server
class UserServerMetadata(BaseModel):
    is_admin: bool = Field(default=False)


class User(BaseModel):
    id: str
    primary_email_verified: bool
    primary_email_auth_enabled: bool
    signed_up_at_millis: float
    last_active_at_millis: float
    is_anonymous: bool
    primary_email: str | None = Field(default=None)
    display_name: str | None = Field(default=None)
    # selected_team_id: str | None = Field(default=None)
    profile_image_url: str | None = Field(default=None)
    client_metadata: UserClientMetadata | None = Field(default=None)
    client_read_only_metadata: UserClientReadOnlyMetadata | None = Field(default=None)
    server_metadata: UserServerMetadata | None = Field(default=None)


async def get_user(settings: Settings, access_token: str, user_id: str) -> User | None:
    headers = build_headers(settings, access_token=access_token)
    response = await _request("GET", f"/api/v1/users/{user_id}", headers)
    if response.status_code == 401:
        return None
    response.raise_for_status()
    return User.model_validate(obj=response.json())


async def get_me(settings: Settings, access_token: str) -> User | None:
    return await get_user(settings, access_token=access_token, user_id="me")


async def delete_user(settings: Settings, access_token: str, user_id: str) -> bool:
    """Delete a user from Stack Auth. Returns True if successful."""
    headers = build_headers(settings, access_token=access_token)
    response = await _request("DELETE", f"/api/v1/users/{user_id}", headers)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True
