"""HTTP utilities for document fetching and URL handling."""

import io
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException, status
from loguru import logger
from pydantic import HttpUrl

from yapit.gateway.metrics import log_event


async def download_document(url: HttpUrl, max_size: int) -> tuple[bytes, str]:
    """Download a document from URL within size limits.

    Args:
        url: URL to download from
        max_size: Maximum allowed file size in bytes

    Returns:
        tuple of (content bytes, content-type header)

    Raises:
        HTTPException: If download fails or file is too large
    """
    headers = {"User-Agent": "Yapit/1.0 (https://yapit.md; document fetcher)"}
    start = time.monotonic()
    async with httpx.AsyncClient(
        proxy="http://smokescreen:4750",
        follow_redirects=True,
        timeout=30.0,
        headers=headers,
    ) as client:
        try:
            head_response = await client.head(str(url))
            if head_response.status_code != 200:
                logger.debug(f"HEAD request failed with {head_response.status_code}, falling back to GET")
            else:
                content_length = head_response.headers.get("content-length")
                if content_length and int(content_length) > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large: {int(content_length)} bytes exceeds maximum of {max_size} bytes",
                    )
            response = await client.get(str(url))
            response.raise_for_status()
            content = io.BytesIO()
            downloaded = 0
            async for chunk in response.aiter_bytes(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large: downloaded {downloaded} bytes exceeds maximum of {max_size} bytes",
                    )
                content.write(chunk)
            content_bytes = content.getvalue()
            header_type = response.headers.get("content-type", "application/octet-stream")
            sniffed_type = sniff_content_type(content_bytes)
            content_type = sniffed_type if sniffed_type else header_type
            duration_ms = int((time.monotonic() - start) * 1000)
            await log_event(
                "url_fetch",
                duration_ms=duration_ms,
                data={"content_type": content_type, "size_bytes": len(content_bytes)},
            )
            return content_bytes, content_type
        except httpx.HTTPStatusError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            code = e.response.status_code
            await log_event("url_fetch", duration_ms=duration_ms, status_code=code, data={"error": "http_status"})
            detail = get_http_error_message(code)
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
        except httpx.RequestError as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            await log_event(
                "url_fetch", duration_ms=duration_ms, status_code=0, data={"error": "request_error", "detail": str(e)}
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unable to reach URL - check it's correct and accessible",
            )


def sniff_content_type(content: bytes) -> str | None:
    """Detect content type from magic bytes. Returns None if unknown."""
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image/gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    head = content[:1024].lstrip()
    if head.startswith(b"<!DOCTYPE") or head.startswith(b"<html") or head.startswith(b"<HTML"):
        return "text/html"
    return None


def get_http_error_message(status_code: int) -> str:
    """Return a user-friendly error message for HTTP status codes."""
    messages = {
        300: "Document has multiple versions - try a more specific URL",
        301: "Page has moved permanently",
        302: "Page has moved temporarily",
        400: "Invalid request to the website",
        401: "This page requires authentication",
        403: "Access to this page is forbidden",
        404: "Page not found - check the URL",
        407: "URL points to a blocked destination",
        408: "Request timed out - the website took too long to respond",
        410: "This page no longer exists",
        429: "Site is rate limiting requests - try again later",
        451: "Content unavailable for legal reasons",
        500: "The target website is having internal issues - try again later",
        502: "The target website's server is not responding - try again later",
        503: "The target website is temporarily unavailable - try again later",
        504: "The target website took too long to respond - try again later",
    }
    if status_code in messages:
        return messages[status_code]
    if 400 <= status_code < 500:
        return f"Website returned client error (HTTP {status_code})"
    if 500 <= status_code < 600:
        return f"Website returned server error (HTTP {status_code})"
    return f"URL returned unexpected status: HTTP {status_code}"


def resolve_relative_urls(markdown: str, base_url: str) -> str:
    """Resolve relative URLs in markdown images and links to absolute URLs.

    When converting webpages, MarkItDown preserves URLs as-is. Relative paths
    like `/images/foo.png` would resolve to Yapit's domain when rendered in the browser.
    This function resolves them to absolute URLs using the source webpage's URL.

    Also:
    - Encodes spaces in URLs since markdown parsers don't handle unencoded spaces
    - Converts same-page links (https://site.com/page/#section) to anchor links (#section)
    """
    parsed_base = urlparse(base_url)
    base_without_fragment = f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_base.path}"
    base_normalized = base_without_fragment.rstrip("/")

    def make_resolver(is_image: bool):
        def resolve(match: re.Match) -> str:
            text, url = match.group(1), match.group(2)
            url_encoded = url.replace(" ", "%20")

            if url.startswith(("#", "data:")):
                prefix = "!" if is_image else ""
                return f"{prefix}[{text}]({url_encoded})"

            # Check if it's an absolute URL pointing to same page with fragment
            if url.startswith(("http://", "https://")):
                parsed = urlparse(url)
                url_without_fragment = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                if url_without_fragment == base_normalized and parsed.fragment:
                    # Same page anchor - convert to just the fragment
                    return f"[{text}](#{parsed.fragment})"
                # Different page - keep as external link
                prefix = "!" if is_image else ""
                return f"{prefix}[{text}]({url_encoded})"

            # Relative URL - resolve against base
            resolved = urljoin(base_url, url_encoded)
            # Check if resolved URL points to same page (for relative anchors like /page/#section)
            parsed_resolved = urlparse(resolved)
            resolved_without_fragment = (
                f"{parsed_resolved.scheme}://{parsed_resolved.netloc}{parsed_resolved.path}".rstrip("/")
            )
            if resolved_without_fragment == base_normalized and parsed_resolved.fragment:
                return f"[{text}](#{parsed_resolved.fragment})"
            prefix = "!" if is_image else ""
            return f"{prefix}[{text}]({resolved})"

        return resolve

    # Images: ![alt](url) - MarkItDown doesn't output titles, so just match to closing paren
    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", make_resolver(True), markdown)
    # Links: [text](url)
    markdown = re.sub(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", make_resolver(False), markdown)
    return markdown
