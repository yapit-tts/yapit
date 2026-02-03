"""Website content extraction. Trafilatura primary, MarkItDown fallback."""

import asyncio
import io
import re
from typing import Any

import trafilatura
from loguru import logger
from markitdown import MarkItDown

from yapit.gateway.document.http import resolve_relative_urls
from yapit.gateway.document.markxiv import detect_arxiv_url, fetch_from_markxiv
from yapit.gateway.document.playwright_renderer import render_with_js

_JS_RENDERING_PATTERNS = [
    r"marked\.parse",
    r"markdown-it",
    r"renderMarkdown",
    r"ReactDOM\.render",
    r"createRoot",
    r"createApp\s*\(",
    r"ng-app",
    r"\.mount\s*\(",
]
_JS_PATTERN_REGEX = re.compile("|".join(_JS_RENDERING_PATTERNS), re.IGNORECASE)


def extract_markdown(html: str, **kwargs: Any) -> str | None:
    """Extract article content from HTML as markdown using trafilatura."""
    kwargs.setdefault("include_links", True)
    kwargs.setdefault("include_tables", True)
    kwargs.setdefault("include_images", True)
    return trafilatura.extract(html, output_format="markdown", **kwargs)


def _needs_js_rendering(html: str, markdown: str | None, content_size: int) -> bool:
    """Detect if a page likely needs JavaScript rendering."""
    if _JS_PATTERN_REGEX.search(html):
        return True
    return not markdown and content_size > 5000


async def extract_website_content(
    content: bytes,
    url: str | None,
    markxiv_url: str | None,
) -> tuple[str, str]:
    """Extract markdown from website content. Returns (markdown, extraction_method)."""
    arxiv_match = detect_arxiv_url(url) if url else None
    if arxiv_match and markxiv_url:
        arxiv_id, _ = arxiv_match
        return await fetch_from_markxiv(markxiv_url, arxiv_id), "markxiv"

    html_str = content.decode("utf-8", errors="ignore")
    markdown = await asyncio.to_thread(extract_markdown, html_str)

    rendered_html = None
    if url and _needs_js_rendering(html_str, markdown, len(content)):
        logger.info(f"JS rendering detected, using Playwright for {url}")
        rendered_html = await render_with_js(url)
        markdown = await asyncio.to_thread(extract_markdown, rendered_html)

    extraction_method = "trafilatura"
    if not markdown:
        logger.info(f"Trafilatura returned None, falling back to MarkItDown for {url}")
        mid = MarkItDown(enable_plugins=False)
        fallback_content = rendered_html.encode("utf-8") if rendered_html else content
        result = await asyncio.to_thread(mid.convert_stream, io.BytesIO(fallback_content))
        markdown = result.markdown
        extraction_method = "markitdown"

    if url:
        markdown = resolve_relative_urls(markdown, url)

    return markdown, extraction_method
