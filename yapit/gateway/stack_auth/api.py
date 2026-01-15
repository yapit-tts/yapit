from typing import Any

from yapit.gateway.config import Settings


def build_headers(settings: Settings, access_token: str) -> dict[str, Any]:
    return {
        "x-stack-access-type": "server",
        "x-stack-project-id": settings.stack_auth_project_id,
        "x-stack-secret-server-key": settings.stack_auth_server_key,
        "x-stack-access-token": access_token,
    }
