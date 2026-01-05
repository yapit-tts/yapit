"""Shared fixtures and utilities for integration tests."""

import asyncio
import json
import os
import subprocess
import uuid

import pytest
import requests
import websockets


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
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=200.0, headers=headers) as client:
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


@pytest.fixture
async def test_document(admin_client):
    """Create a test document for admin."""
    response = await admin_client.post(
        "/v1/documents/text",
        json={"content": "Hello integration test!"},
    )
    assert response.status_code == 201
    doc = response.json()

    # Fetch blocks separately
    blocks_response = await admin_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    doc["blocks"] = blocks_response.json()

    return doc


@pytest.fixture
async def unique_document(regular_client):
    """Create a document with unique text for regular user."""
    import time

    unique_text = f"Unique test content {time.time()} {uuid.uuid4()}"
    response = await regular_client.post(
        "/v1/documents/text",
        json={"content": unique_text},
    )
    assert response.status_code == 201
    doc = response.json()

    # Fetch blocks separately
    blocks_response = await regular_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    doc["blocks"] = blocks_response.json()

    return doc


@pytest.fixture
async def regular_document(regular_client):
    """Create a regular test document using regular client."""
    response = await regular_client.post(
        "/v1/documents/text",
        json={"content": "Hello, I need credits!"},
    )
    assert response.status_code == 201
    doc = response.json()

    # Fetch blocks separately
    blocks_response = await regular_client.get(f"/v1/documents/{doc['id']}/blocks")
    assert blocks_response.status_code == 200
    doc["blocks"] = blocks_response.json()

    return doc


class TTSWebSocketClient:
    """WebSocket client for TTS synthesis testing."""

    def __init__(self, ws):
        self.ws = ws
        self.messages: list[dict] = []
        self._listener_task = None

    async def start_listening(self):
        """Start background listener for incoming messages."""
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        """Listen for messages and store them."""
        try:
            async for msg in self.ws:
                self.messages.append(json.loads(msg))
        except websockets.ConnectionClosed:
            pass

    async def synthesize(
        self,
        document_id: str,
        block_indices: list[int],
        model: str = "kokoro",
        voice: str = "af_heart",
        synthesis_mode: str = "server",
        cursor: int | None = None,
    ) -> None:
        """Send synthesize request."""
        await self.ws.send(
            json.dumps(
                {
                    "type": "synthesize",
                    "document_id": document_id,
                    "block_indices": block_indices,
                    "cursor": cursor if cursor is not None else (block_indices[0] if block_indices else 0),
                    "model": model,
                    "voice": voice,
                    "synthesis_mode": synthesis_mode,
                }
            )
        )

    async def cursor_moved(self, document_id: str, cursor: int) -> None:
        """Send cursor_moved message for eviction."""
        await self.ws.send(
            json.dumps(
                {
                    "type": "cursor_moved",
                    "document_id": document_id,
                    "cursor": cursor,
                }
            )
        )

    async def wait_for_status(self, block_idx: int, status: str, timeout: float = 60.0) -> dict | None:
        """Wait for a specific block status message."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for msg in self.messages:
                if msg.get("type") == "status" and msg.get("block_idx") == block_idx and msg.get("status") == status:
                    return msg
            await asyncio.sleep(0.1)
        return None

    async def wait_for_any_status(self, block_idx: int, timeout: float = 10.0) -> dict | None:
        """Wait for any status message for a block."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for msg in self.messages:
                if msg.get("type") == "status" and msg.get("block_idx") == block_idx:
                    return msg
            await asyncio.sleep(0.1)
        return None

    async def wait_for_evicted(self, timeout: float = 5.0) -> dict | None:
        """Wait for an evicted message."""
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for msg in self.messages:
                if msg.get("type") == "evicted":
                    return msg
            await asyncio.sleep(0.1)
        return None

    def get_evicted_messages(self) -> list[dict]:
        """Get all evicted messages received."""
        return [msg for msg in self.messages if msg.get("type") == "evicted"]

    def get_status_messages(self, block_idx: int | None = None) -> list[dict]:
        """Get all status messages, optionally filtered by block_idx."""
        msgs = [msg for msg in self.messages if msg.get("type") == "status"]
        if block_idx is not None:
            msgs = [msg for msg in msgs if msg.get("block_idx") == block_idx]
        return msgs

    async def close(self):
        """Close the connection."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        await self.ws.close()


async def make_ws_client(auth_token: str):
    """Create a WebSocket client for TTS."""
    ws = await websockets.connect(
        f"ws://localhost:8000/v1/ws/tts?token={auth_token}",
        close_timeout=5,
    )
    client = TTSWebSocketClient(ws)
    await client.start_listening()
    return client


@pytest.fixture
async def admin_ws_client(admin_user):
    """WebSocket client authenticated as admin user."""
    client = await make_ws_client(admin_user["token"])
    yield client
    await client.close()


@pytest.fixture
async def regular_ws_client(regular_user):
    """WebSocket client authenticated as regular user."""
    client = await make_ws_client(regular_user["token"])
    yield client
    await client.close()
