"""Defuddle integration for website content extraction."""

import httpx
from fastapi import HTTPException, status
from loguru import logger

from yapit.gateway.metrics import log_event


async def extract_with_defuddle(defuddle_url: str, html: str, url: str | None) -> str | None:
    """Extract markdown from HTML via the defuddle sidecar.

    Returns markdown string, or None if extraction returned empty content.
    Raises HTTPException(503) if the sidecar is unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{defuddle_url}/extract",
                json={"html": html, "url": url},
            )
    except httpx.TimeoutException:
        await log_event("defuddle_error", data={"url": url, "error": "timeout"})
        logger.error(f"Defuddle timeout for {url}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content extraction service timed out. Please try again.",
        )
    except httpx.RequestError as e:
        await log_event("defuddle_error", data={"url": url, "error": "connection", "detail": str(e)})
        logger.error(f"Defuddle connection error for {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Content extraction service unavailable. Please try again in a few seconds.",
        )

    if not response.is_success:
        await log_event("defuddle_error", data={"url": url, "error": "extraction", "status": response.status_code})
        logger.error(f"Defuddle error for {url}: {response.status_code} {response.text}")
        return None

    data = response.json()
    markdown = data.get("markdown", "")
    return markdown if markdown.strip() else None
