import logging
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from yapit.gateway.stack_auth import User, get_me

bearer = HTTPBearer(auto_error=False)

LOGGER = logging.getLogger("auth")
LOGGER.setLevel(logging.DEBUG)


async def authenticate(
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
) -> User:
    if creds is None:
        LOGGER.debug("no credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await get_me(access_token=creds.credentials)
    if user is None:
        LOGGER.debug("no user returned")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
