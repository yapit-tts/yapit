import logging
from typing import Any
from yapit.gateway.config import get_settings

AUTH_LOGGER = logging.getLogger("auth")


def build_headers(access_token: str) -> dict[str, Any]:
    SETTINGS = get_settings()

    return {
        "x-stack-access-type": "server",
        "x-stack-project-id": SETTINGS.stack_auth_project_id,
        "x-stack-secret-server-key": SETTINGS.stack_auth_server_key,
        "x-stack-access-token": access_token,
    }
