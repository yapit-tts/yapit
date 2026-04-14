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


async def close_defuddle_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def extract_website(
    url: str | None = None, *, html: str | None = None, timeout_ms: int = 30_000
) -> tuple[str, str | None, str]:
    """Extract markdown via the defuddle service.

    Pass url for a live fetch (cascade: static → bot → playwright),
    or html for pre-fetched/uploaded content (parsed directly, no fetch).

    Third return value is the extraction method.
    """
    assert _client is not None, "Call init_defuddle_client() during app startup"
    assert url or html, "Either url or html is required"

    label = url or "(uploaded HTML)"
    body: dict = {"timeout_ms": timeout_ms}
    if html:
        body["html"] = html
        if url:
            body["url"] = url
    else:
        body["url"] = url

    try:
        resp = await _client.post("/extract", json=body, timeout=timeout_ms / 1000 + 5)
    except Exception:
        logger.exception(f"Defuddle service unreachable for {label}")
        raise

    if resp.status_code == 503:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content extraction service is busy — please try again in a moment",
        )
    if not resp.is_success:
        logger.error(f"Defuddle service returned {resp.status_code} for {label}")
        resp.raise_for_status()

    data = resp.json()
    markdown = data.get("markdown", "")
    title = data.get("title")
    method = data.get("extraction_method", "unknown")

    logger.info(f"Extracted {label} via {method} ({len(markdown)} chars)")
    return markdown, title, method
