"""Website content extraction. Trafilatura primary, html2text fallback."""

import asyncio
import re

import html2text
import trafilatura
from loguru import logger

from yapit.gateway.document.http import resolve_relative_urls
from yapit.gateway.document.markxiv import detect_arxiv_url, fetch_from_markxiv
from yapit.gateway.document.playwright_renderer import render_with_js
from yapit.gateway.metrics import log_event

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


def _extract_with_trafilatura(html: str) -> str | None:
    return trafilatura.extract(
        html, output_format="markdown", include_links=True, include_tables=True, include_images=True
    )


def _has_js_framework(html: str) -> bool:
    return bool(_JS_PATTERN_REGEX.search(html))


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

    # JS framework detected in raw HTML — render with Playwright before extraction
    used_playwright = False
    if url and _has_js_framework(html_str):
        logger.info(f"JS framework patterns detected, using Playwright for {url}")
        try:
            html_str = await render_with_js(url)
            used_playwright = True
        except Exception:
            logger.warning(f"Playwright render failed for {url}, continuing with static HTML")

    markdown = await asyncio.to_thread(_extract_with_trafilatura, html_str)

    # Trafilatura got nothing — might be JS-rendered content we missed
    if not markdown and url and not used_playwright:
        logger.info(f"Trafilatura returned None on large page, trying Playwright for {url}")
        try:
            html_str = await render_with_js(url)
        except Exception:
            logger.warning(f"Playwright render failed for {url}, continuing with static HTML")
        else:
            markdown = await asyncio.to_thread(_extract_with_trafilatura, html_str)

    extraction_method = "trafilatura"
    if not markdown:
        logger.warning(f"Trafilatura returned None, falling back to html2text for {url}")
        await log_event("html_fallback_triggered", data={"url": url})
        converter = html2text.HTML2Text()
        converter.body_width = 0
        markdown = converter.handle(html_str)
        extraction_method = "html2text"

    if url:
        markdown = resolve_relative_urls(markdown, url)

    return markdown, extraction_method
