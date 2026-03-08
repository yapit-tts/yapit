"""Website content extraction via the defuddle service.

The defuddle service runs Playwright + Chromium in an isolated container.
The gateway calls it over HTTP to extract markdown from URLs.
"""

import time

import httpx
from loguru import logger

from yapit.gateway.metrics import log_event

_client: httpx.AsyncClient | None = None


def init_defuddle_client(base_url: str) -> None:
    global _client
    _client = httpx.AsyncClient(base_url=base_url)


async def extract_website(url: str, timeout_ms: int = 30_000) -> tuple[str, str | None]:
    """Extract markdown from a URL via the defuddle service.

    Returns (markdown, title). Markdown is empty string if extraction fails.
    """
    assert _client is not None, "Call init_defuddle_client() during app startup"

    t0 = time.monotonic()
    try:
        resp = await _client.post(
            "/extract",
            json={"url": url, "timeout_ms": timeout_ms},
            timeout=timeout_ms / 1000 + 10,
        )
        resp.raise_for_status()
        data = resp.json()
        markdown = data.get("markdown", "")
        title = data.get("title")

        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info(f"Extracted {url} in {duration_ms}ms ({len(markdown)} chars)")
        await log_event("website_extraction", data={"url": url, "chars": len(markdown), "duration_ms": duration_ms})
        return markdown, title

    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.error(f"Defuddle service call failed for {url} after {duration_ms}ms: {e}")
        await log_event("website_extraction_error", data={"url": url, "error": str(e), "duration_ms": duration_ms})
        return "", None
