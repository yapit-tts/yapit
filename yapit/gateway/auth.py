from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Literal
from pydantic import BaseModel, Field
import requests

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from yapit.gateway.config import get_settings

logger = logging.getLogger("auth")

bearer = HTTPBearer(auto_error=False)


# visible to the client
# editable by the client
class ClientMetadata(BaseModel): ...


# visible to the client
# editable by the server
class ClientReadOnlyMetadata(BaseModel):
    tier: Literal["free", "pro"] | None = Field(default=None)


# visible to the server
# editable by the server
class ServerMetadata(BaseModel): ...


class User(BaseModel):
    id: str
    primary_email_verified: bool
    primary_email_auth_enabled: bool
    signed_up_at_millis: float
    last_active_at_millis: float
    is_anonymous: bool
    primary_email: str | None = Field(default=None)
    display_name: str | None = Field(default=None)
    selected_team_id: str | None = Field(default=None)
    profile_image_url: str | None = Field(default=None)
    client_metadata: ClientMetadata | None = Field(default=None)
    client_read_only_metadata: ClientReadOnlyMetadata | None = Field(default=None)
    server_metadata: ServerMetadata | None = Field(default=None)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
) -> User:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = authenticate(creds.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@lru_cache(maxsize=1024)
def authenticate(token: str) -> User | None:
    # https://docs.stack-auth.com/next/concepts/backend-integration

    settings = get_settings()

    url = f"{settings.stack_auth_host}/api/v1/users/me"
    headers = {
        "x-stack-access-type": "server",
        "x-stack-project-id": settings.stack_auth_project_id,
        "x-stack-secret-server-key": settings.stack_auth_server_key,
        "x-stack-access-token": token,
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()

        body = response.json()
        return User.model_validate(obj=body)
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.HTTPError:
        return None
    except requests.exceptions.RequestException:
        return None
    except Exception as ex:
        logging.error("unexpected error in authenticate", exc_info=ex)
        return None
