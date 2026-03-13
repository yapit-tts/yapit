"""Website content extraction via the defuddle service.

The defuddle service extracts markdown from URLs using a cascade:
static fetch + linkedom → bot UA retry → Playwright browser fallback.
The gateway calls it over HTTP — the cascade is handled internally.
"""

import time

import httpx
from fastapi import HTTPException, status
from loguru import logger

from yapit.gateway.metrics import log_event

_client: httpx.AsyncClient | None = None


def init_defuddle_client(base_url: str) -> None:
    global _client
    _client = httpx.AsyncClient(base_url=base_url)


async def extract_website(url: str, timeout_ms: int = 30_000) -> tuple[str, str | None]:
    """Extract markdown from a URL via the defuddle service.

    Returns (markdown, title). Raises HTTPException on service errors.
    """
    assert _client is not None, "Call init_defuddle_client() during app startup"

    t0 = time.monotonic()
    resp = await _client.post(
        "/extract",
        json={"url": url, "timeout_ms": timeout_ms},
        timeout=timeout_ms / 1000 + 5,
    )
    if resp.status_code == 503:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content extraction service is busy — please try again in a moment",
        )
    resp.raise_for_status()
    data = resp.json()
    markdown = data.get("markdown", "")
    title = data.get("title")
    method = data.get("extraction_method", "unknown")

    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(f"Extracted {url} via {method} in {duration_ms}ms ({len(markdown)} chars)")
    await log_event(
        "website_extraction", data={"url": url, "chars": len(markdown), "duration_ms": duration_ms, "method": method}
    )
    return markdown, title
