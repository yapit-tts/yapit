import requests

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from yapit.gateway.config import ANON_USER, get_settings

# TODO(lukas): implement JWT auth
bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Security(bearer),
) -> str:
    if creds is None:
        # TODO(lukas): error if unauthenticated
        assert ANON_USER.id is not None
        return ANON_USER.id
    raise NotImplementedError()


# TODO: cache tokens s.t. requests close in time are faster
def authenticate(token: str) -> str | None:
    # https://docs.stack-auth.com/next/concepts/backend-integration

    settings = get_settings()

    # TODO(lukas): maybe cache this to prevent multiple allocs
    url = f"{settings.stack_auth_host}/api/v1/users/me"
    headers = {
        "x-stack-access-type": "server",
        "x-stack-project-id": settings.stack_auth_project_id,
        "x-stack-secret-server-key": settings.stack_auth_server_key,
        "x-stack-access-token": token,
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        # stack-auth returns non-ok code if code is invalid
        return None

    body = response.json()
    return body["id"]
