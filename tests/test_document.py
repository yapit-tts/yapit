from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from gateway.api.v1 import routers
from gateway.db import get_db
from gateway.domain.models import User

ANON_ID = "anonymous_user"


# ---------- in-memory DB fixture ----------
@pytest.fixture(scope="session")
def async_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True, echo=False)
    return eng


@pytest.fixture(scope="function")
async def db(async_engine):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # seed anon user
        await conn.run_sync(lambda s: s.add(User(id=ANON_ID, email="anon@example.com", tier="free")))
    async_session = AsyncSession(async_engine, expire_on_commit=False)
    try:
        yield async_session
    finally:
        await async_session.close()


# ---------- FastAPI app wired to test DB ----------
@pytest.fixture(scope="function")
def app(db: AsyncSession):
    test_app = FastAPI()
    for r in routers:
        test_app.include_router(r)

    async def _override() -> AsyncSession:
        return db

    test_app.dependency_overrides[get_db] = _override
    return test_app


# ---------- sync TestClient ----------
@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


# ---------- actual tests ----------
# TODO: this fails, but curl works:
# curl -X 'POST' \
#   'http://127.0.0.1:8000/v1/documents' \
#   -H 'accept: application/json' \
#   -H 'Content-Type: application/json' \
#   -d '{
#   "source_type": "paste",
#   "text_content": "string"
# }'
def test_create_document_ok(client: TestClient):
    resp = client.post(
        "/v1/documents",
        json={
            "source_type": "paste",
            "text_content": "Hello world. " * 10,
            "source_ref": None,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["num_blocks"] > 0
    assert data["est_duration_ms"] > 0
    assert len(data["document_id"]) == 36  # UUID4


def test_url_not_implemented(client: TestClient):
    resp = client.post(
        "/v1/documents",
        json={"source_type": "url", "source_ref": "https://example.com"},
    )
    assert resp.status_code == 501
