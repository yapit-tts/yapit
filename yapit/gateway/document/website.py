"""Website content extraction via Playwright + defuddle."""

from yapit.gateway.document.http import resolve_relative_urls
from yapit.gateway.document.playwright_renderer import extract_website


async def extract_website_content(url: str) -> tuple[str, str | None, str]:
    """Extract markdown from a website URL. Returns (markdown, title, extraction_method)."""
    markdown, title = await extract_website(url)

    if url and markdown:
        markdown = resolve_relative_urls(markdown, url)

    return markdown, title, "defuddle"
