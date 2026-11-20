"""The gateway's Web Bot Auth signatures, against outputs of Cloudflare's own implementations.

Ed25519 signatures are deterministic, so given the same key, parameters and nonce, ours must match theirs byte
for byte. The key is the RFC 9421 test key (appendix B.1.4).
"""

import base64
import secrets
import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from yapit.gateway import web_bot_auth
from yapit.gateway.web_bot_auth import directory_response, load_signing_key, request_signature_headers

RFC_9421_D = "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU"
RFC_9421_KEYID = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"


def rfc_9421_private_key() -> str:
    seed = base64.urlsafe_b64decode(RFC_9421_D + "=")
    der = Ed25519PrivateKey.from_private_bytes(seed).private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    return base64.b64encode(der).decode()


def test_the_key_directory_matches_cloudflares_test_vector():
    # cloudflare/web-bot-auth, packages/web-bot-auth/test/test_data/web_bot_auth_directory_response_v1.json:
    # the passing vector of their http-signature-directory validator.
    key = load_signing_key(rfc_9421_private_key(), "https://signature-agent.test")
    assert key is not None

    body, headers = directory_response(key, now=1735689600, lifetime_s=4889289600 - 1735689600)

    assert body == (
        b'{"keys":[{"kty":"OKP","crv":"Ed25519","kid":"poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U",'
        b'"x":"JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs","use":"sig"}]}'
    )
    assert headers["Content-Type"] == "application/http-message-signatures-directory+json"
    assert headers["Content-Digest"] == "sha-256=:CADMT2aBdV/rqQr/NIru64ERQkCobVvllA4V0fLFDu0=:"
    assert headers["Signature-Input"] == (
        'binding0=("@authority";req "content-digest");created=1735689600;'
        'keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=4889289600;'
        'tag="http-message-signatures-directory"'
    )
    assert headers["Signature"] == (
        "binding0=:yiHq0TXrbpzbmlttAQMpYoAufitFJUWuNsakB7QQMoN0EHbo5o51bZRVR8az/ptTWCwllix9clrKXfGKwdPzBg==:"
    )


def test_a_request_signature_matches_cloudflares_signer():
    # web-bot-auth 0.2.0's sign(), for GET https://example.com/post with Signature-Agent "https://yapit.md",
    # created 1795210000, expires 60 s later, and a nonce of 64 bytes of 0x07.
    key = load_signing_key(rfc_9421_private_key(), "https://yapit.md")
    assert key is not None
    nonce = base64.b64encode(bytes([7] * 64)).decode()

    headers = request_signature_headers(key, "example.com", now=1795210000, nonce=nonce)

    assert headers["Signature-Agent"] == '"https://yapit.md"'
    assert headers["Signature-Input"] == (
        f'sig1=("@authority" "signature-agent");created=1795210000;keyid="{RFC_9421_KEYID}";alg="ed25519";'
        f'expires=1795210060;nonce="{nonce}";tag="web-bot-auth"'
    )
    assert headers["Signature"] == (
        "sig1=:5SxoG8hYhVlNy9JxPGYFVyOy7F6xMcvdqkrKY9FRzRKTetNHm30bihFYdwh38xJKqB5EZdzA5ZiPfXpLzpogBQ==:"
    )


def test_a_port_other_than_the_default_is_part_of_the_signed_authority():
    # web-bot-auth 0.2.0's sign(), as above, for https://example.com:8443/post.
    key = load_signing_key(rfc_9421_private_key(), "https://yapit.md")
    assert key is not None
    nonce = base64.b64encode(bytes([7] * 64)).decode()

    headers = request_signature_headers(key, "example.com:8443", now=1795210000, nonce=nonce)

    assert headers["Signature"] == (
        "sig1=:QTFzF9wZuNEjhIz7ZicjWyY+XU9LSZKvs2+E38xxddkl/eHVcA+7eoe4g9NEW9qdMJ535OMW9VJjxhKlVGQWAQ==:"
    )


def test_a_self_hosted_instance_without_a_key_sends_requests_unsigned(monkeypatch):
    monkeypatch.setattr(web_bot_auth, "_key", load_signing_key(rfc_9421_private_key(), "https://yapit.md"))
    web_bot_auth.init_web_bot_auth("", "http://localhost")
    assert web_bot_auth.signature_headers("https://example.com/") == {}


async def test_the_signer_signs_the_authority_the_extraction_service_names(monkeypatch):
    monkeypatch.setattr(web_bot_auth, "_key", load_signing_key(rfc_9421_private_key(), "https://yapit.md"))
    async with signer_client() as client:
        response = await client.post("/sign", json={"authority": "example.com:8443"})
    assert response.status_code == 200
    assert response.json()["Signature-Agent"] == '"https://yapit.md"'
    assert 'tag="web-bot-auth"' in response.json()["Signature-Input"]


@pytest.mark.parametrize(
    "authority",
    ['example.com\n"signature-agent": "https://evil.example"', "Example.COM", "example.com/path", "", "a b"],
)
async def test_the_signer_refuses_anything_but_a_bare_authority(monkeypatch, authority):
    monkeypatch.setattr(web_bot_auth, "_key", load_signing_key(rfc_9421_private_key(), "https://yapit.md"))
    async with signer_client() as client:
        response = await client.post("/sign", json={"authority": authority})
    assert response.status_code == 422


def signer_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=web_bot_auth.signer_app), base_url="http://gateway:8002")


@pytest.mark.live
async def test_cloudflare_research_verifies_a_signed_request():
    # The research server checks for the RFC 9421 test key, which its own directory lists, so it is the
    # Signature-Agent here; it answers this sentence to a request it verified.
    research = "https://http-message-signatures-example.research.cloudflare.com/"
    key = load_signing_key(rfc_9421_private_key(), research)
    assert key is not None
    nonce = base64.b64encode(secrets.token_bytes(64)).decode()
    headers = request_signature_headers(key, key.authority, time.time(), nonce)
    async with httpx.AsyncClient(timeout=20) as client:
        page = (await client.get(research, headers=headers)).text
    assert "successfully authenticated as owning the test public key" in page
