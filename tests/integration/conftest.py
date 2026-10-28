"""Shared fixtures and utilities for integration tests."""

import asyncio
import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import websockets
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.domain_models import SubscriptionStatus, UserSubscription

TEST_DATABASE_URL = "postgresql+asyncpg://yapit:yapit@localhost:5432/yapit"


async def provision_subscription(user_id: str, plan_id: int = 2) -> None:
    """Give a test user a subscription. Default plan_id=2 is Basic (unlimited kokoro)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        now = datetime.now(tz=UTC)
        subscription = UserSubscription(
            user_id=user_id,
            plan_id=plan_id,
            status=SubscriptionStatus.active,
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
        )
        session.add(subscription)
        await session.commit()

    await engine.dispose()


def _load_create_user_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "create_user.py"
    spec = importlib.util.spec_from_file_location("create_user", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# In-process, not a subprocess: each subprocess would import the whole gateway again, seconds per user
create_user_script = _load_create_user_script()


async def create_unique_user() -> dict:
    """A new user with an API token minted for it by scripts/create_user.py."""
    test_id = str(uuid.uuid4())[:8]
    email = f"test-{test_id}@example.com"
    user_id, token = await create_user_script.create_user(
        create_user_script.Args(
            email=email, name=f"Test User {test_id}", label="integration-test", database_url=TEST_DATABASE_URL
        )
    )
    return {"id": user_id, "email": email, "token": token}


@pytest.fixture
async def subscribed_user():
    """Create a test user with a Basic subscription (unlimited kokoro)."""
    user_data = await create_unique_user()
    await provision_subscription(user_data["id"])
    return user_data


@pytest.fixture
async def regular_user():
    """Create a unique regular test user."""
    return await create_unique_user()


async def make_client(auth_token: str | None = None):
    """Create an HTTP client with optional authentication."""
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=200.0, headers=headers) as client:
        yield client


@pytest.fixture
async def subscribed_client(subscribed_user):
    """HTTP client authenticated as subscribed user."""
    async for client in make_client(subscribed_user["token"]):
        yield client


@pytest.fixture
async def regular_client(regular_user):
    """HTTP client authenticated as regular user."""
    async for client in make_client(regular_user["token"]):
        yield client


@pytest.fixture
async def test_document(subscribed_client):
    """Create a test document for subscribed user."""
    response = await subscribed_client.post(
        "/v1/documents/text",
        json={"content": "Hello integration test!"},
    )
    assert response.status_code == 201
    doc = response.json()

    # Fetch blocks separately
    blocks_response = await subscribed_client.get(f"/v1/documents/{doc['id']}/blocks")
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
    ) -> None:
        """Send synthesize request."""
        await self.ws.send(
            json.dumps(
                {
                    "type": "synthesize",
                    "document_id": document_id,
                    "block_indices": block_indices,
                    "model": model,
                    "voice": voice,
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
        "ws://localhost:8000/v1/ws/tts",
        additional_headers={"Authorization": f"Bearer {auth_token}"},
        close_timeout=5,
    )
    client = TTSWebSocketClient(ws)
    await client.start_listening()
    return client


@pytest.fixture
async def subscribed_ws_client(subscribed_user):
    """WebSocket client authenticated as subscribed user."""
    client = await make_ws_client(subscribed_user["token"])
    yield client
    await client.close()


@pytest.fixture
async def regular_ws_client(regular_user):
    """WebSocket client authenticated as regular user."""
    client = await make_ws_client(regular_user["token"])
    yield client
    await client.close()
