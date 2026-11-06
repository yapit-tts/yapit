"""Passkeys through the gateway's API, against a software authenticator that signs as a security key would."""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from tests.yapit.gateway.api.conftest import APP_URL, SAME_ORIGIN, settings_changed, sign_in, signed_in_user
from yapit.gateway.domain_models import Passkey, UserAccount

RP_ID = "yapit.test"

UP, UV, AT = 0x01, 0x04, 0x40  # authenticator data flags: user present, user verified, attested credential data


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class Authenticator:
    """One discoverable ES256 credential, made on `create` and used on `get`, the way a YubiKey answers the browser."""

    origin: str = APP_URL
    flags: int = UP | UV
    counter: int | None = 0  # None: keeps no counter and always reports 0, like a synced passkey
    key: ec.EllipticCurvePrivateKey = field(default_factory=lambda: ec.generate_private_key(ec.SECP256R1()))
    credential_id: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    user_handle: bytes | None = None

    def create(self, options: dict) -> dict:
        assert options["rp"]["id"] == RP_ID
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["authenticatorSelection"]["userVerification"] == "required"
        self.user_handle = unb64url(options["user"]["id"])
        numbers = self.key.public_key().public_numbers()
        cose_key = {1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")}
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + cbor2.dumps(cose_key)
        auth_data = self._auth_data(self.flags | AT) + attested
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": b64url(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})),
                "transports": ["usb", "nfc"],
            },
            "clientExtensionResults": {},
        }

    def get(self, options: dict) -> dict:
        assert options["rpId"] == RP_ID
        assert options["userVerification"] == "required"
        assert not options.get("allowCredentials"), "sign-in lists no credentials: the browser offers what it holds"
        if self.counter is not None:
            self.counter += 1
        auth_data = self._auth_data(self.flags)
        client_data = self._client_data("webauthn.get", options["challenge"])
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        assert self.user_handle is not None
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(self.user_handle),
            },
            "clientExtensionResults": {},
        }

    def _auth_data(self, flags: int) -> bytes:
        count = self.counter or 0
        return hashlib.sha256(RP_ID.encode()).digest() + bytes([flags]) + count.to_bytes(4, "big")

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()


async def add_passkey(browser, authenticator: Authenticator, label: str = "YubiKey") -> httpx.Response:
    started = await browser.post("/v1/auth/passkeys/register/options", headers=SAME_ORIGIN)
    assert started.status_code == 200, started.text
    body = started.json()
    return await browser.post(
        "/v1/auth/passkeys",
        json={"flow": body["flow"], "credential": authenticator.create(body["options"]), "label": label},
        headers=SAME_ORIGIN,
    )


async def passkey_sign_in(browser, authenticator: Authenticator) -> httpx.Response:
    started = await browser.post("/v1/auth/passkeys/sign-in/options", headers=SAME_ORIGIN)
    assert started.status_code == 200, started.text
    body = started.json()
    return await browser.post(
        "/v1/auth/passkeys/sign-in",
        json={"flow": body["flow"], "credential": authenticator.get(body["options"])},
        headers=SAME_ORIGIN,
    )


@pytest.fixture
async def other_browser(app, real_auth):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as client:
        yield client


@pytest.fixture
def key() -> Authenticator:
    return Authenticator()


async def test_a_passkey_added_on_the_account_page_signs_in_another_browser(browser, other_browser, app, key, session):
    user = await sign_in(browser, app, "reader@example.com")
    added = await add_passkey(browser, key)
    assert added.status_code == 201, added.text
    assert added.json()["label"] == "YubiKey"

    signed_in = await passkey_sign_in(other_browser, key)

    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["id"] == user["id"]
    assert (await signed_in_user(other_browser))["id"] == user["id"]
    stored = await session.get_one(Passkey, b64url(key.credential_id))
    assert stored.transports == ["usb", "nfc"]
    assert stored.sign_count == 1
    assert stored.last_used is not None


async def test_the_session_says_passkeys_work_on_https(browser):
    assert (await browser.get("/v1/auth/session")).json()["passkeys"] is True


@pytest.mark.parametrize("app_url", ["http://192.168.1.20", "http://yapit.lan:8080"])
async def test_passkeys_are_off_on_plain_http_away_from_localhost(browser, app, app_url):
    with settings_changed(app, app_url=app_url):
        assert (await browser.get("/v1/auth/session")).json()["passkeys"] is False
        assert (await browser.post("/v1/auth/passkeys/sign-in/options")).status_code == 404


async def test_localhost_counts_as_secure(browser, app):
    with settings_changed(app, app_url="http://localhost:5173"):
        assert (await browser.get("/v1/auth/session")).json()["passkeys"] is True


async def test_an_authenticator_without_a_counter_signs_in_every_time(browser, other_browser, app):
    synced = Authenticator(counter=None)
    await sign_in(browser, app, "reader@example.com")
    assert (await add_passkey(browser, synced)).status_code == 201

    for _ in range(3):
        assert (await passkey_sign_in(other_browser, synced)).status_code == 200


async def test_a_counter_that_goes_back_is_refused_as_a_cloned_key(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)
    assert (await passkey_sign_in(other_browser, key)).status_code == 200
    assert (await passkey_sign_in(other_browser, key)).status_code == 200

    key.counter = 0  # the next `get` answers 1, below the 2 already seen
    refused = await passkey_sign_in(other_browser, key)

    assert refused.status_code == 400
    assert await signed_in_user(other_browser) is not None  # still the earlier session, nothing new


async def test_a_passkey_yapit_does_not_know_is_refused(other_browser, key):
    key.user_handle = b"someone"
    refused = await passkey_sign_in(other_browser, key)
    assert refused.status_code == 400
    assert "does not know this passkey" in refused.json()["detail"]
    assert await signed_in_user(other_browser) is None


async def test_a_sign_in_without_user_verification_is_refused(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)

    key.flags = UP  # touched, but no PIN or fingerprint
    assert (await passkey_sign_in(other_browser, key)).status_code == 400
    assert await signed_in_user(other_browser) is None


async def test_registration_without_user_verification_is_refused(browser, app):
    await sign_in(browser, app, "reader@example.com")
    assert (await add_passkey(browser, Authenticator(flags=UP))).status_code == 400


async def test_an_answer_signed_for_another_site_is_refused(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)

    key.origin = "https://yapit.test.evil.example"
    assert (await passkey_sign_in(other_browser, key)).status_code == 400
    assert await signed_in_user(other_browser) is None


async def test_each_challenge_works_once(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)
    started = (await other_browser.post("/v1/auth/passkeys/sign-in/options")).json()
    answer = {"flow": started["flow"], "credential": key.get(started["options"])}

    first = await other_browser.post("/v1/auth/passkeys/sign-in", json=answer, headers=SAME_ORIGIN)
    replayed = await other_browser.post("/v1/auth/passkeys/sign-in", json=answer, headers=SAME_ORIGIN)

    assert first.status_code == 200
    assert replayed.status_code == 400


async def test_a_sign_in_flow_cannot_register_a_passkey(browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    started = (await browser.post("/v1/auth/passkeys/sign-in/options")).json()
    registration = (await browser.post("/v1/auth/passkeys/register/options", headers=SAME_ORIGIN)).json()

    added = await browser.post(
        "/v1/auth/passkeys",
        json={"flow": started["flow"], "credential": key.create(registration["options"]), "label": "x"},
        headers=SAME_ORIGIN,
    )

    assert added.status_code == 400


async def test_a_passkey_answering_with_another_users_handle_is_refused(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)

    key.user_handle = b"another-user-id"
    assert (await passkey_sign_in(other_browser, key)).status_code == 400


async def test_another_users_registration_flow_is_refused(browser, other_browser, app, key):
    await sign_in(browser, app, "first@example.com")
    await sign_in(other_browser, app, "second@example.com")
    started = (await browser.post("/v1/auth/passkeys/register/options", headers=SAME_ORIGIN)).json()

    hijacked = await other_browser.post(
        "/v1/auth/passkeys",
        json={"flow": started["flow"], "credential": key.create(started["options"]), "label": "x"},
        headers=SAME_ORIGIN,
    )

    assert hijacked.status_code == 400


async def test_the_same_passkey_cannot_be_added_twice(browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    assert (await add_passkey(browser, key)).status_code == 201

    started = (await browser.post("/v1/auth/passkeys/register/options", headers=SAME_ORIGIN)).json()
    assert [c["id"] for c in started["options"]["excludeCredentials"]] == [b64url(key.credential_id)]
    again = await browser.post(
        "/v1/auth/passkeys",
        json={"flow": started["flow"], "credential": key.create(started["options"]), "label": "again"},
        headers=SAME_ORIGIN,
    )
    assert again.status_code == 400


async def test_sign_in_from_another_site_is_refused(other_browser, browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)
    started = (await other_browser.post("/v1/auth/passkeys/sign-in/options")).json()

    refused = await other_browser.post(
        "/v1/auth/passkeys/sign-in",
        json={"flow": started["flow"], "credential": key.get(started["options"])},
        headers={"Origin": "https://evil.example"},
    )

    assert refused.status_code == 403


async def test_adding_a_passkey_needs_a_signed_in_account(other_browser):
    assert (await other_browser.post("/v1/auth/passkeys/register/options", headers=SAME_ORIGIN)).status_code == 401


async def test_passkeys_are_listed_renamed_and_removed(browser, other_browser, app, key):
    await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key, label="Keychain YubiKey")
    passkey_id = b64url(key.credential_id)

    listed = (await browser.get("/v1/auth/passkeys")).json()
    assert [(p["id"], p["label"]) for p in listed] == [(passkey_id, "Keychain YubiKey")]

    renamed = await browser.patch(f"/v1/auth/passkeys/{passkey_id}", json={"label": "Backup"}, headers=SAME_ORIGIN)
    assert renamed.status_code == 204
    assert (await browser.get("/v1/auth/passkeys")).json()[0]["label"] == "Backup"

    assert (await browser.delete(f"/v1/auth/passkeys/{passkey_id}", headers=SAME_ORIGIN)).status_code == 204
    assert (await browser.get("/v1/auth/passkeys")).json() == []
    assert (await passkey_sign_in(other_browser, key)).status_code == 400


async def test_another_users_passkey_cannot_be_renamed_or_removed(browser, other_browser, app, key):
    await sign_in(browser, app, "first@example.com")
    await add_passkey(browser, key)
    await sign_in(other_browser, app, "second@example.com")
    passkey_id = b64url(key.credential_id)

    renamed = await other_browser.patch(f"/v1/auth/passkeys/{passkey_id}", json={"label": "mine"}, headers=SAME_ORIGIN)
    removed = await other_browser.delete(f"/v1/auth/passkeys/{passkey_id}", headers=SAME_ORIGIN)

    assert (renamed.status_code, removed.status_code) == (404, 404)
    assert (await browser.get("/v1/auth/passkeys")).json()[0]["label"] == "YubiKey"


async def test_deleting_the_account_removes_its_passkeys(browser, app, key, session):
    user = await sign_in(browser, app, "reader@example.com")
    await add_passkey(browser, key)

    await session.delete(await session.get_one(UserAccount, user["id"]))
    await session.commit()

    assert await session.get(Passkey, b64url(key.credential_id)) is None
