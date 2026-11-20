"""The gateway's Web Bot Auth signatures, against outputs of Cloudflare's own implementations.

Ed25519 signatures are deterministic, so given the same key, parameters and nonce, ours must match theirs byte
for byte. The key is the RFC 9421 test key (appendix B.1.4).
"""

import base64

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

    body, headers = directory_response(key, "signature-agent.test", now=1735689600, lifetime_s=4889289600 - 1735689600)

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

    headers = request_signature_headers(key, "https://example.com/post", now=1795210000, nonce=nonce)

    assert headers["Signature-Agent"] == '"https://yapit.md"'
    assert headers["Signature-Input"] == (
        f'sig1=("@authority" "signature-agent");created=1795210000;keyid="{RFC_9421_KEYID}";alg="ed25519";'
        f'expires=1795210060;nonce="{nonce}";tag="web-bot-auth"'
    )
    assert headers["Signature"] == (
        "sig1=:5SxoG8hYhVlNy9JxPGYFVyOy7F6xMcvdqkrKY9FRzRKTetNHm30bihFYdwh38xJKqB5EZdzA5ZiPfXpLzpogBQ==:"
    )


def test_without_a_key_requests_go_out_unsigned(monkeypatch):
    monkeypatch.setattr(web_bot_auth, "_key", None)
    web_bot_auth.init_web_bot_auth("", "http://localhost")
    assert web_bot_auth.signature_headers("https://example.com/") == {}


def test_a_key_needs_an_https_origin_to_name():
    with pytest.raises(ValueError, match="https"):
        load_signing_key(rfc_9421_private_key(), "http://localhost")
