import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from yapit.gateway import web_bot_auth

DIRECTORY = "/.well-known/http-message-signatures-directory"


@pytest.fixture
def throwaway_key(monkeypatch):
    der = Ed25519PrivateKey.generate().private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    monkeypatch.setattr(
        web_bot_auth, "_key", web_bot_auth.load_signing_key(base64.b64encode(der).decode(), "https://yapit.example")
    )


@pytest.mark.asyncio
async def test_the_directory_proves_its_key_for_app_urls_host_whatever_host_is_asked(client, throwaway_key):
    response = await client.get(DIRECTORY, headers={"Host": "mirror.example"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/http-message-signatures-directory+json"
    assert response.headers["content-digest"] == (
        f"sha-256=:{base64.b64encode(hashlib.sha256(response.content).digest()).decode()}:"
    )
    [jwk] = response.json()["keys"]
    assert (jwk["kty"], jwk["crv"]) == ("OKP", "Ed25519")
    params = response.headers["signature-input"].removeprefix("binding0=")
    assert f'keyid="{jwk["kid"]}"' in params
    assert 'tag="http-message-signatures-directory"' in params
    # The signature base as RFC 9421 lays it out, as in Cloudflare's directory test vector.
    base = (
        f'"@authority";req: yapit.example\n"content-digest": {response.headers["content-digest"]}\n'
        f'"@signature-params": {params}'
    )
    signature = base64.b64decode(response.headers["signature"].removeprefix("binding0=:").removesuffix(":"))
    public_key = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(jwk["x"] + "="))
    public_key.verify(signature, base.encode())


@pytest.mark.asyncio
async def test_without_a_key_the_directory_is_not_found(client, monkeypatch):
    monkeypatch.setattr(web_bot_auth, "_key", None)
    response = await client.get(DIRECTORY)
    assert response.status_code == 404
