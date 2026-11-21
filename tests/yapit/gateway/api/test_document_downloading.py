import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from fastapi import HTTPException

from yapit.gateway import web_bot_auth
from yapit.gateway.api.v1.documents import _extract_document_info
from yapit.gateway.document import defuddle_client
from yapit.gateway.document import http as http_module
from yapit.gateway.document.http import download_document

MAX_SIZE = 100 * 1024 * 1024


@pytest.fixture
def web(monkeypatch):
    """A stub site behind the download's client, and a stub extraction service answering its robots.txt checks.

    Tests set `web.routes[url] = httpx.Response(...)` and `web.refused` to the URLs robots.txt refuses.
    """
    web = SimpleNamespace(routes={}, refused=set(), seen=[])

    def site(request: httpx.Request) -> httpx.Response:
        web.seen.append(request)
        if str(request.url) not in web.routes:
            raise httpx.ConnectError("unreachable", request=request)
        return web.routes[str(request.url)]

    def extraction_service(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["url"] in web.refused:
            return httpx.Response(422, json={"error": "This site's robots.txt does not allow yapit to fetch this page"})
        return httpx.Response(200, json={})

    monkeypatch.setattr(http_module, "fetch_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(site)))
    monkeypatch.setattr(
        defuddle_client,
        "_client",
        httpx.AsyncClient(base_url="http://defuddle", transport=httpx.MockTransport(extraction_service)),
    )
    monkeypatch.setattr(http_module, "log_event", AsyncMock())
    return web


class TestDownloadDocument:
    @pytest.mark.asyncio
    async def test_successful_download(self, web):
        web.routes["https://example.com/test.pdf"] = httpx.Response(
            200, headers={"content-type": "application/pdf"}, content=b"Test PDF content"
        )

        content, content_type = await download_document("https://example.com/test.pdf", MAX_SIZE)

        assert content == b"Test PDF content"
        assert content_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_size_limit_from_content_length(self, web):
        web.routes["https://example.com/huge.pdf"] = httpx.Response(
            200, headers={"content-type": "application/pdf", "content-length": "200000000"}, content=b"x"
        )

        with pytest.raises(HTTPException, match="File too large"):
            await download_document("https://example.com/huge.pdf", MAX_SIZE)

    @pytest.mark.asyncio
    async def test_size_limit_while_streaming(self, web):
        web.routes["https://example.com/test.pdf"] = httpx.Response(
            200, headers={"content-type": "application/pdf"}, stream=_chunks(b"x" * 8192, 200)
        )

        with pytest.raises(HTTPException, match="File too large"):
            await download_document("https://example.com/test.pdf", 1024 * 1024)

    @pytest.mark.asyncio
    async def test_http_error(self, web):
        web.routes["https://example.com/missing.pdf"] = httpx.Response(
            404, headers={"content-type": "application/json"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await download_document("https://example.com/missing.pdf", MAX_SIZE)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_network_error(self, web):
        with pytest.raises(HTTPException) as exc_info:
            await download_document("https://unreachable.example/test.pdf", MAX_SIZE)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_no_content_type(self, web):
        web.routes["https://example.com/test"] = httpx.Response(200, content=b"Some content")

        content, content_type = await download_document("https://example.com/test", MAX_SIZE)

        assert content == b"Some content"
        assert content_type == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_page_robots_refuses_is_never_requested(self, web):
        web.routes["https://example.com/private"] = httpx.Response(200, content=b"secret")
        web.refused = {"https://example.com/private"}

        with pytest.raises(HTTPException, match=r"robots\.txt") as exc_info:
            await download_document("https://example.com/private", MAX_SIZE)

        assert exc_info.value.status_code == 422
        assert web.seen == []

    @pytest.mark.asyncio
    async def test_redirect_into_a_refused_page_stops_before_requesting_it(self, web):
        web.routes["https://example.com/old"] = httpx.Response(302, headers={"location": "/private"})
        web.routes["https://example.com/private"] = httpx.Response(200, content=b"secret")
        web.refused = {"https://example.com/private"}

        with pytest.raises(HTTPException, match=r"robots\.txt"):
            await download_document("https://example.com/old", MAX_SIZE)

        assert [str(r.url) for r in web.seen] == ["https://example.com/old"]

    @pytest.mark.asyncio
    async def test_a_cloudflare_challenge_is_reported_as_bot_protection(self, web):
        web.routes["https://protected.example/post"] = httpx.Response(
            403,
            headers={"content-type": "text/html", "cf-mitigated": "challenge"},
            content=b"<title>Just a moment...</title>",
        )

        with pytest.raises(HTTPException, match="bot protection") as exc_info:
            await download_document("https://protected.example/post", MAX_SIZE)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_with_a_key_each_hop_is_signed_for_its_own_authority(self, web, monkeypatch):
        private = Ed25519PrivateKey.generate()
        der = private.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
        monkeypatch.setattr(
            web_bot_auth, "_key", web_bot_auth.load_signing_key(base64.b64encode(der).decode(), "https://yapit.md")
        )
        web.routes["https://short.example/x"] = httpx.Response(301, headers={"location": "https://example.com/doc"})
        web.routes["https://example.com/doc"] = httpx.Response(200, headers={"content-type": "application/pdf"})

        await download_document("https://short.example/x", MAX_SIZE)

        for request in web.seen:
            assert request.headers["signature-agent"] == '"https://yapit.md"'
            params = request.headers["signature-input"].removeprefix("sig1=")
            base = f'"@authority": {request.url.host}\n"signature-agent": "https://yapit.md"\n"@signature-params": {params}'
            signature = base64.b64decode(request.headers["signature"].removeprefix("sig1=:").removesuffix(":"))
            private.public_key().verify(signature, base.encode())
        assert [r.url.host for r in web.seen] == ["short.example", "example.com"]


class TestExtractDocumentInfo:
    """Test _extract_document_info function."""

    def test_extract_pdf_info(self):
        """Test extracting info from PDF."""
        # Read actual test PDF
        with open("tests/fixtures/documents/minimal.pdf", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "application/pdf")

        assert page_count == 1
        assert title == "Test PDF Title"

    def test_extract_pdf_info_multipage(self):
        """Test extracting info from multi-page PDF."""
        with open("tests/fixtures/documents/multipage.pdf", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "application/pdf")

        assert page_count == 3
        assert title == "Multi-page Test PDF"

    def test_extract_html_info(self):
        """Test extracting info from HTML."""
        content = b"""<!DOCTYPE html>
        <html>
        <head>
            <title>Test HTML Title</title>
        </head>
        <body>Content</body>
        </html>"""

        page_count, title = _extract_document_info(content, "text/html")

        assert page_count == 1
        assert title == "Test HTML Title"

    def test_extract_html_no_title(self):
        """Test extracting info from HTML without title."""
        content = b"<html><body>No title here</body></html>"

        page_count, title = _extract_document_info(content, "text/html")

        assert page_count == 1
        assert title is None

    def test_extract_image_info(self):
        """Test extracting info from image."""
        # Read actual test image
        with open("tests/fixtures/documents/test.png", "rb") as f:
            content = f.read()

        page_count, title = _extract_document_info(content, "image/png")

        assert page_count == 1
        assert title is None

    def test_extract_unsupported_type(self):
        """Test handling of unsupported content types."""
        content = b"Some content"

        with pytest.raises(HTTPException, match="Unsupported content type for metadata extraction: application/json"):
            _extract_document_info(content, "application/json")


class _chunks(httpx.AsyncByteStream):
    def __init__(self, chunk: bytes, count: int):
        self.chunk, self.count = chunk, count

    async def __aiter__(self):
        for _ in range(self.count):
            yield self.chunk
