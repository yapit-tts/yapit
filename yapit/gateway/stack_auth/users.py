from typing import Literal

import httpx
from pydantic import BaseModel, Field

from yapit.gateway.config import Settings
from yapit.gateway.stack_auth.api import build_headers


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
    url = f"{settings.stack_auth_api_host}/api/v1/users/{user_id}"
    headers = build_headers(settings, access_token=access_token)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    if response.status_code == 401:
        return None
    response.raise_for_status()

    body = response.json()
    return User.model_validate(obj=body)


async def get_me(settings: Settings, access_token: str) -> User | None:
    return await get_user(settings, access_token=access_token, user_id="me")


async def delete_user(settings: Settings, access_token: str, user_id: str) -> bool:
    """Delete a user from Stack Auth. Returns True if successful."""
    url = f"{settings.stack_auth_api_host}/api/v1/users/{user_id}"
    headers = build_headers(settings, access_token=access_token)

    async with httpx.AsyncClient() as client:
        response = await client.request("DELETE", url, headers=headers)
    if response.status_code == 404:
        return False  # User already deleted
    response.raise_for_status()
    return True
