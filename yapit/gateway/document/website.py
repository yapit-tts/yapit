"""Website content extraction via defuddle service."""

from fastapi import HTTPException, status

from yapit.gateway.document.defuddle_client import extract_website
from yapit.gateway.document.http import resolve_relative_urls


async def extract_website_content(url: str | None = None, *, html: str | None = None) -> tuple[str, str | None, str]:
    """Extract markdown from a website URL or raw HTML. Raises HTTPException if no content."""
    markdown, title, method = await extract_website(url, html=html)

    if not markdown.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Could not extract readable content from this page",
        )

    if url:
        markdown = resolve_relative_urls(markdown, url)
    return markdown, title, method
