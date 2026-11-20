"""Website content extraction via the defuddle service.

The defuddle service extracts markdown from URLs using a cascade:
static fetch + linkedom → bot UA retry → Playwright browser fallback.
The gateway calls it over HTTP — the cascade is handled internally.
It also answers the gateway's robots.txt checks.
A page it will not fetch comes back as a 422 whose message is for the reader.
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


async def assert_robots_allow(url: str) -> None:
    """Raise a 422 naming robots.txt where the site's robots.txt keeps yapit from fetching url."""
    assert _client is not None, "Call init_defuddle_client() during app startup"
    try:
        resp = await _client.post("/robots", json={"url": url}, timeout=15)
    except httpx.RequestError:
        logger.exception(f"Defuddle service unreachable for the robots.txt check of {url}")
        resp = None
    if resp is not None:
        _raise_refusal(resp)
    # Our own service failing is not the page's failure, so it must not read as one to the reader.
    if resp is None or not resp.is_success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not check this site's robots.txt right now - please try again in a moment",
        )


def _raise_refusal(resp: httpx.Response) -> None:
    if resp.status_code == 422:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=resp.json()["error"])


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

    _raise_refusal(resp)
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
