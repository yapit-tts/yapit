"""Web Bot Auth: signatures that let a site verify a request came from this yapit, and the key directory they name.

Both are RFC 9421 HTTP Message Signatures, as Cloudflare's Web Bot Auth page profiles them. The extraction
service signs its own requests the same way (docker/defuddle/signature.js).
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_der_private_key

DIRECTORY_PATH = "/.well-known/http-message-signatures-directory"
DIRECTORY_CONTENT_TYPE = "application/http-message-signatures-directory+json"
REQUEST_LIFETIME_S = 60
DIRECTORY_LIFETIME_S = 3600


@dataclass(frozen=True)
class SigningKey:
    private: Ed25519PrivateKey
    x: str  # the public key, base64url without padding
    keyid: str  # its JWK thumbprint (RFC 8037, appendix A.3)
    authority: str  # APP_URL's host, which serves the key directory


def load_signing_key(private_key: str, app_url: str) -> SigningKey | None:
    """The key from a base64 PKCS#8 DER Ed25519 private key; None when private_key is empty."""
    if not private_key:
        return None
    key = load_der_private_key(base64.b64decode(private_key), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("WEB_BOT_AUTH_PRIVATE_KEY is not an Ed25519 key")
    origin = urlsplit(app_url)
    # Cloudflare fails a Signature-Agent that is not https.
    if origin.scheme != "https":
        raise ValueError("APP_URL must be https to sign requests")
    x = _b64url(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    thumbprint = hashlib.sha256(json.dumps({"crv": "Ed25519", "kty": "OKP", "x": x}, separators=(",", ":")).encode())
    return SigningKey(
        private=key,
        x=x,
        keyid=_b64url(thumbprint.digest()),
        authority=_authority(app_url),
    )


def request_signature_headers(key: SigningKey, url: str, now: float, nonce: str) -> dict[str, str]:
    """Signature, Signature-Input and Signature-Agent for a request to url."""
    created = int(now)
    params = (
        f'("@authority" "signature-agent");created={created};keyid="{key.keyid}";alg="ed25519"'
        f';expires={created + REQUEST_LIFETIME_S};nonce="{nonce}";tag="web-bot-auth"'
    )
    signature_agent = f'"https://{key.authority}"'
    base = f'"@authority": {_authority(url)}\n"signature-agent": {signature_agent}\n"@signature-params": {params}'
    return {
        "Signature-Agent": signature_agent,
        "Signature-Input": f"sig1={params}",
        "Signature": f"sig1=:{_sign(key, base)}:",
    }


def directory_response(
    key: SigningKey, now: float, lifetime_s: int = DIRECTORY_LIFETIME_S
) -> tuple[bytes, dict[str, str]]:
    """The key directory's body and headers.

    The proof is signed over APP_URL's host, whatever host the request named, and over the body's digest, so a
    copy served from another host or with other keys does not verify.
    """
    jwk = {"kty": "OKP", "crv": "Ed25519", "kid": key.keyid, "x": key.x, "use": "sig"}
    body = json.dumps({"keys": [jwk]}, separators=(",", ":")).encode()
    content_digest = f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    created = int(now)
    params = (
        f'("@authority";req "content-digest");created={created};keyid="{key.keyid}";alg="ed25519"'
        f';expires={created + lifetime_s};tag="http-message-signatures-directory"'
    )
    base = f'"@authority";req: {key.authority}\n"content-digest": {content_digest}\n"@signature-params": {params}'
    return body, {
        "Content-Type": DIRECTORY_CONTENT_TYPE,
        "Content-Digest": content_digest,
        "Signature-Input": f"binding0={params}",
        "Signature": f"binding0=:{_sign(key, base)}:",
    }


_key: SigningKey | None = None


def init_web_bot_auth(private_key: str, app_url: str) -> None:
    global _key
    _key = load_signing_key(private_key, app_url)


def signing_key() -> SigningKey | None:
    return _key


def signature_headers(url: str) -> dict[str, str]:
    """The signature headers for a request to url, or none where no key is configured."""
    if _key is None:
        return {}
    return request_signature_headers(_key, url, time.time(), base64.b64encode(secrets.token_bytes(64)).decode())


def _authority(url: str) -> str:
    """The URL's host as sent on the wire (IDNA-encoded, IPv6 bracketed), with its port unless the scheme's default."""
    parsed = httpx.URL(url)
    host = parsed.raw_host.decode()
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def _sign(key: SigningKey, base: str) -> str:
    return base64.b64encode(key.private.sign(base.encode())).decode()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
