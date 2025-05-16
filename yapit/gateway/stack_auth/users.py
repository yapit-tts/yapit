import logging
from typing import Literal
from pydantic import BaseModel, Field
import requests

from yapit.gateway.stack_auth.api import build_headers
from yapit.gateway.config import get_settings


# visible to the client
# editable by the client
class UserClientMetadata(BaseModel): ...


# visible to the client
# editable by the server
class UserClientReadOnlyMetadata(BaseModel):
    tier: Literal["free", "pro"] | None = Field(default=None)


# visible to the server
# editable by the server
class UserServerMetadata(BaseModel): ...


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


async def get_user(access_token: str, user_id: str) -> User | None:
    SETTINGS = get_settings()

    url = f"{SETTINGS.stack_auth_host}/api/v1/users/{user_id}"
    headers = build_headers(access_token=access_token)

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        body = response.json()
        return User.model_validate(obj=body)
    except requests.exceptions.Timeout as ex:
        logging.error("requesting stack-auth timed out", exc_info=ex)
        return None
    except requests.exceptions.HTTPError as ex:
        logging.error("stack-auth http request failed", exc_info=ex)
        return None
    except requests.exceptions.RequestException:
        return None
    except Exception as ex:
        logging.error("unexpected error in authenticate", exc_info=ex)
        return None


async def get_me(access_token: str) -> User | None:
    return await get_user(access_token=access_token, user_id="me")
