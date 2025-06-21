"""Shared fixtures and utilities for integration tests."""

import os
import subprocess
import uuid

import pytest
import requests


def get_stack_auth_config():
    """Get Stack Auth configuration from environment."""
    return {
        "api_host": os.getenv("DEV_STACK_AUTH_API_HOST", "http://localhost:8102"),
        "project_id": os.getenv("STACK_AUTH_PROJECT_ID"),
        "server_key": os.getenv("STACK_AUTH_SERVER_KEY"),
        "client_key": os.getenv("STACK_AUTH_CLIENT_KEY"),
    }


def create_unique_user(is_admin: bool = False) -> dict:
    """Create a unique user for testing and return user info."""
    # Generate unique email
    test_id = str(uuid.uuid4())[:8]
    email = f"test-{test_id}@example.com"
    password = "test-password-123"
    display_name = f"Test User {test_id}"

    # Call create_user script with arguments
    cmd = ["python", "scripts/create_user.py", "--email", email, "--password", password, "--display-name", display_name]
    if not is_admin:
        cmd.append("--no-admin")

    # Run the script and capture user_id from stderr
    result = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ})

    if result.returncode != 0:
        raise RuntimeError(f"Failed to create user: {result.stdout}\n{result.stderr}")

    # Get user_id from stderr (last line)
    user_id = result.stderr.strip().split("\n")[-1]

    return {
        "id": user_id,
        "email": email,
        "password": password,
    }


def get_auth_token(email: str, password: str) -> str:
    """Get access token for a user."""
    config = get_stack_auth_config()

    if not config["project_id"] or not config["client_key"]:
        raise RuntimeError("Missing STACK_AUTH_PROJECT_ID or STACK_AUTH_CLIENT_KEY")

    headers = {
        "X-Stack-Access-Type": "client",
        "X-Stack-Project-Id": config["project_id"],
        "X-Stack-Publishable-Client-Key": config["client_key"],
    }

    r = requests.post(
        f"{config['api_host']}/api/v1/auth/password/sign-in",
        headers=headers,
        json={"email": email, "password": password},
    )

    if r.status_code not in [200, 201]:
        raise RuntimeError(f"Failed to sign in: {r.status_code} {r.text}")

    return r.json()["access_token"]


@pytest.fixture
def admin_user():
    """Create a unique admin test user."""
    user_data = create_unique_user(is_admin=True)
    user_data["token"] = get_auth_token(user_data["email"], user_data["password"])
    return user_data


@pytest.fixture
def regular_user():
    """Create a unique regular test user."""
    user_data = create_unique_user(is_admin=False)
    user_data["token"] = get_auth_token(user_data["email"], user_data["password"])
    return user_data


async def make_client(auth_token: str = None):
    """Create an HTTP client with optional authentication."""
    import httpx

    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=70.0, headers=headers) as client:
        yield client


@pytest.fixture
async def admin_client(admin_user):
    """HTTP client authenticated as admin user."""
    async for client in make_client(admin_user["token"]):
        yield client


@pytest.fixture
async def regular_client(regular_user):
    """HTTP client authenticated as regular user."""
    async for client in make_client(regular_user["token"]):
        yield client


async def create_document(client, text: str = "Hello integration test!"):
    """Helper to create a document with specified text."""
    response = await client.post(
        "/v1/documents",
        json={"source_type": "paste", "text_content": text},
    )
    assert response.status_code == 201
    return response.json()


async def create_unique_document(client):
    """Helper to create a document with unique text to avoid caching."""
    import time

    unique_text = f"Unique test content {time.time()} {uuid.uuid4()}"
    return await create_document(client, unique_text)
