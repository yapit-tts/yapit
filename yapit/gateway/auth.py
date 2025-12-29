import logging
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Security, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yapit.gateway.config import Settings, get_settings
from yapit.gateway.stack_auth import User, get_me

bearer = HTTPBearer(auto_error=False)

LOGGER = logging.getLogger("auth")
LOGGER.setLevel(logging.DEBUG)

ANONYMOUS_ID_PREFIX = "anon-"


def create_anonymous_user(anonymous_id: str) -> User:
    """Create an anonymous user with the given ID."""
    return User(
        id=f"{ANONYMOUS_ID_PREFIX}{anonymous_id}",
        primary_email_verified=False,
        primary_email_auth_enabled=False,
        signed_up_at_millis=time.time() * 1000,
        last_active_at_millis=time.time() * 1000,
        is_anonymous=True,
    )


async def authenticate(
    settings: Annotated[Settings, Depends(get_settings)],
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
    x_anonymous_id: str | None = Header(None, alias="X-Anonymous-ID"),
) -> User:
    # Try Bearer token first (authenticated user)
    if creds is not None:
        user = await get_me(settings, access_token=creds.credentials)
        if user is not None:
            return user
        LOGGER.debug("Bearer token invalid or expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fall back to anonymous ID
    if x_anonymous_id is not None:
        LOGGER.debug(f"Anonymous user: {x_anonymous_id[:8]}...")
        return create_anonymous_user(x_anonymous_id)

    # No auth at all
    LOGGER.debug("no credentials provided")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate_ws(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Authenticate WebSocket connection via query param token or anonymous ID."""
    token = websocket.query_params.get("token")
    anonymous_id = websocket.query_params.get("anonymous_id")

    if token:
        try:
            user = await get_me(settings, access_token=token)
            if user is not None:
                return user
            LOGGER.warning("WS auth: get_me returned None for token")
        except Exception as e:
            LOGGER.error(f"WS auth: get_me raised exception: {e}")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")

    if anonymous_id:
        return create_anonymous_user(anonymous_id)

    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Not authenticated")
