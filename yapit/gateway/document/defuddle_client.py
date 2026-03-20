"""Website content extraction via the defuddle service.

The defuddle service extracts markdown from URLs using a cascade:
static fetch + linkedom → bot UA retry → Playwright browser fallback.
The gateway calls it over HTTP — the cascade is handled internally.
"""

import httpx
from fastapi import HTTPException, status
from loguru import logger

_client: httpx.AsyncClient | None = None


def init_defuddle_client(base_url: str) -> None:
    global _client
    _client = httpx.AsyncClient(base_url=base_url)


async def extract_website(url: str, timeout_ms: int = 30_000) -> tuple[str, str | None, str]:
    """Extract markdown from a URL via the defuddle service.

    Third return value is the cascade step (static, static-bot, playwright).
    """
    assert _client is not None, "Call init_defuddle_client() during app startup"

    try:
        resp = await _client.post(
            "/extract",
            json={"url": url, "timeout_ms": timeout_ms},
            timeout=timeout_ms / 1000 + 5,
        )
    except Exception as e:
        logger.error(f"Defuddle service unreachable for {url}: {e}")
        raise

    if resp.status_code == 503:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content extraction service is busy — please try again in a moment",
        )
    if not resp.is_success:
        logger.error(f"Defuddle service returned {resp.status_code} for {url}")
        resp.raise_for_status()

    data = resp.json()
    markdown = data.get("markdown", "")
    title = data.get("title")
    method = data.get("extraction_method", "unknown")

    logger.info(f"Extracted {url} via {method} ({len(markdown)} chars)")
    return markdown, title, method
