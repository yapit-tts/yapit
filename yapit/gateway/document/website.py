"""Website content extraction via defuddle sidecar."""

import re
from urllib.parse import urljoin

import httpx
from loguru import logger

from yapit.gateway.document.defuddle import extract_with_defuddle
from yapit.gateway.document.http import resolve_relative_urls
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

_MD_RENDERER_PATTERNS = re.compile(r"marked\.parse|markdown-it|renderMarkdown", re.IGNORECASE)
_MD_FETCH_PATTERN = re.compile(r"""fetch\s*\(\s*['"]([^'"]+\.(?:md|markdown|mdx))['"]""")


def _has_js_framework(html: str) -> bool:
    return bool(_JS_PATTERN_REGEX.search(html))


def _find_md_source_url(html: str, page_url: str) -> str | None:
    """Detect pages that fetch a separate .md file for client-side rendering.

    Only triggers when inline scripts contain both a markdown renderer
    (marked.parse, markdown-it, renderMarkdown) and a fetch for a .md file.
    Returns the resolved absolute URL of the .md file, or None.
    """
    if not _MD_RENDERER_PATTERNS.search(html):
        return None

    match = _MD_FETCH_PATTERN.search(html)
    if not match:
        return None

    md_path = match.group(1)
    resolved = urljoin(page_url, md_path)
    logger.info(f"Detected markdown source fetch: {md_path} -> {resolved}")
    return resolved


async def _fetch_md_source(url: str) -> str | None:
    """Fetch a .md source file directly. Returns markdown text or None."""
    try:
        async with httpx.AsyncClient(
            proxy="http://smokescreen:4750",
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": "Yapit/1.0 (https://yapit.md; document fetcher)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            text = resp.text

            if "text/html" in content_type and text.strip().startswith("<"):
                return None

            return text
    except Exception as e:
        logger.warning(f"Failed to fetch markdown source {url}: {e}")
        return None


async def extract_website_content(
    content: bytes,
    url: str | None,
    defuddle_url: str | None = None,
) -> tuple[str, str]:
    """Extract markdown from website content. Returns (markdown, extraction_method)."""
    html_str = content.decode("utf-8", errors="ignore")

    # JS framework detected in raw HTML — try .md source shortcut first
    used_playwright = False
    if url and _has_js_framework(html_str):
        md_source_url = _find_md_source_url(html_str, url)
        if md_source_url:
            markdown = await _fetch_md_source(md_source_url)
            if markdown:
                markdown = resolve_relative_urls(markdown, url)
                return markdown, "md_source"

        # No .md source found or fetch failed — render with Playwright
        logger.info(f"JS framework patterns detected, using Playwright for {url}")
        try:
            html_str = await render_with_js(url)
            used_playwright = True
        except Exception:
            logger.warning(f"Playwright render failed for {url}, continuing with static HTML")

    if not defuddle_url:
        logger.error("No defuddle_url configured, cannot extract website content")
        await log_event("defuddle_error", data={"url": url, "error": "not_configured"})
        return html_str, "raw"

    markdown = await extract_with_defuddle(defuddle_url, html_str, url)

    # Defuddle got nothing — might be JS-rendered content we missed
    if not markdown and url and not used_playwright:
        logger.info(f"Defuddle returned None, trying Playwright for {url}")
        try:
            html_str = await render_with_js(url)
        except Exception:
            logger.warning(f"Playwright render failed for {url}")
        else:
            markdown = await extract_with_defuddle(defuddle_url, html_str, url)

    if not markdown:
        logger.warning(f"Defuddle returned no content for {url}")
        await log_event("defuddle_empty", data={"url": url})
        return "", "defuddle"

    if url:
        markdown = resolve_relative_urls(markdown, url)

    return markdown, "defuddle"
