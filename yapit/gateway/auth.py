from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yapit.gateway.config import ANON_USER

# TODO implement JWT auth
bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
) -> str:
    if creds is None:
        return ANON_USER.id
    raise NotImplementedError()
