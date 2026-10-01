"""Stack Auth access tokens checked against the project's key set.

Tokens here are built the way Stack Auth's backend builds them (apps/backend/src/lib/tokens.tsx):
ES256, the key id in the header, the project id as audience for signed-up users, and
`<project>:anon` / `<project>:restricted` audiences signed with keys of their own.
"""

import json
import time
from types import SimpleNamespace
from typing import cast

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from yapit.gateway.config import Settings
from yapit.gateway.stack_auth import users

PROJECT_ID = "project-1"
SETTINGS = cast(Settings, SimpleNamespace(stack_auth_project_id=PROJECT_ID))


class Key:
    def __init__(self, kid: str):
        self.kid = kid
        self.private = ec.generate_private_key(ec.SECP256R1())

    def public_jwk(self) -> dict:
        jwk = json.loads(ECAlgorithm.to_jwk(self.private.public_key()))
        return {**jwk, "kid": self.kid, "alg": "ES256"}

    def sign(self, audience: str = PROJECT_ID, expires_in: int = 600, **claims) -> str:
        now = int(time.time())
        payload = {
            "sub": "user-1",
            "project_id": PROJECT_ID,
            "branch_id": "main",
            "refresh_token_id": "refresh-1",
            "role": "authenticated",
            "email": "reader@example.com",
            "email_verified": True,
            "is_anonymous": False,
            "is_restricted": False,
            "restricted_reason": None,
            "iss": f"https://auth.example.com/api/v1/projects/{PROJECT_ID}",
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
            **claims,
        }
        return jwt.encode(payload, self.private, algorithm="ES256", headers={"kid": self.kid})


@pytest.fixture
def key_set(monkeypatch):
    """The project's published keys, served to the gateway; `fetches` counts requests for them."""
    published: list[Key] = [Key("normal-old"), Key("normal-new")]
    fetches = []

    async def fake_request(method, url, headers):
        fetches.append(url)
        assert url == f"/api/v1/projects/{PROJECT_ID}/.well-known/jwks.json"
        return httpx.Response(
            200, json={"keys": [k.public_jwk() for k in published]}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(users, "_request", fake_request)
    monkeypatch.setattr(users, "_signing_keys", {})
    monkeypatch.setattr(users, "_signing_keys_fetched_at", float("-inf"))
    return SimpleNamespace(published=published, fetches=fetches)


async def test_signed_up_users_token_gives_that_user(key_set):
    user = await users.verify_access_token(SETTINGS, key_set.published[0].sign())
    assert user == users.User(id="user-1", is_anonymous=False, primary_email="reader@example.com")


async def test_key_set_is_fetched_once_for_many_requests(key_set):
    for key in key_set.published * 3:
        assert await users.verify_access_token(SETTINGS, key.sign()) is not None
    assert len(key_set.fetches) == 1


async def test_expired_token_is_rejected(key_set):
    assert await users.verify_access_token(SETTINGS, key_set.published[0].sign(expires_in=-1)) is None


async def test_token_for_another_project_is_rejected(key_set):
    assert await users.verify_access_token(SETTINGS, key_set.published[0].sign(audience="project-2")) is None


async def test_token_without_expiry_is_rejected(key_set):
    key = key_set.published[0]
    token = jwt.encode({"sub": "user-1", "aud": PROJECT_ID}, key.private, algorithm="ES256", headers={"kid": key.kid})
    assert await users.verify_access_token(SETTINGS, token) is None


@pytest.mark.parametrize("audience", [f"{PROJECT_ID}:anon", f"{PROJECT_ID}:restricted"])
async def test_anonymous_and_restricted_users_are_rejected(key_set, audience):
    """Their tokens are signed with keys the project's key set leaves out."""
    token = Key("not-published").sign(audience=audience, is_anonymous=audience.endswith(":anon"), is_restricted=True)
    assert await users.verify_access_token(SETTINGS, token) is None


async def test_tampered_token_is_rejected(key_set):
    header, _, signature = key_set.published[0].sign().split(".")
    forged = jwt.utils.base64url_encode(json.dumps({"sub": "someone-else", "aud": PROJECT_ID}).encode()).decode()
    assert await users.verify_access_token(SETTINGS, f"{header}.{forged}.{signature}") is None


async def test_hmac_token_keyed_with_the_public_key_is_rejected(key_set):
    """The algorithm is pinned to ES256, so a token cannot pick HS256 and sign with public material."""
    key = key_set.published[0]
    public = key.public_jwk()["x"].encode()
    token = jwt.encode(
        {"sub": "attacker", "aud": PROJECT_ID, "exp": int(time.time()) + 600},
        public,
        algorithm="HS256",
        headers={"kid": key.kid},
    )
    assert await users.verify_access_token(SETTINGS, token) is None


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
async def test_garbage_is_rejected_without_asking_stack_auth(key_set, token):
    assert await users.verify_access_token(SETTINGS, token) is None
    assert key_set.fetches == []


async def test_unknown_key_ids_refetch_at_most_once_per_interval(key_set):
    stranger = Key("unknown")
    for _ in range(5):
        assert await users.verify_access_token(SETTINGS, stranger.sign()) is None
    assert len(key_set.fetches) == 1


async def test_key_published_later_is_picked_up_after_the_interval(key_set, monkeypatch):
    assert await users.verify_access_token(SETTINGS, key_set.published[0].sign()) is not None
    rotated = Key("rotated")
    key_set.published.append(rotated)
    assert await users.verify_access_token(SETTINGS, rotated.sign()) is None

    monkeypatch.setattr(users, "_signing_keys_fetched_at", time.monotonic() - users.SIGNING_KEYS_REFETCH_SECONDS)
    assert await users.verify_access_token(SETTINGS, rotated.sign()) is not None
    assert len(key_set.fetches) == 2
