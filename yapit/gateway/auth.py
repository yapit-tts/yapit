import logging
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yapit.gateway.config import Settings, get_settings
from yapit.gateway.stack_auth import User, get_me

bearer = HTTPBearer(auto_error=False)

LOGGER = logging.getLogger("auth")
LOGGER.setLevel(logging.DEBUG)

ANON_USER = User(
    id="",
    primary_email_verified=True,
    primary_email_auth_enabled=True,
    signed_up_at_millis=time.time(),
    last_active_at_millis=time.time(),
    is_anonymous=False,
)


async def authenticate(
    settings: Annotated[Settings, Depends(get_settings)],
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
) -> User:
    if creds is None:
        LOGGER.debug("no credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await get_me(settings, access_token=creds.credentials)
    if user is None:
        LOGGER.debug("no user returned")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
