"""Website content extraction. Trafilatura primary, html2text fallback."""

import asyncio
import re
from copy import deepcopy
from urllib.parse import urljoin

import html2text
import httpx
import trafilatura
from loguru import logger
from lxml import etree  # type: ignore[attr-defined]  # lxml C extension
from trafilatura.xml import xmltotxt

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

_LAYOUT_TABLE_THRESHOLD = 10


def _extract_with_trafilatura(html: str) -> str | None:
    """Extract with trafilatura, fixing layout table paragraph collapse.

    Trafilatura's serializer skips blank lines between paragraphs inside <cell>
    elements (its representation of <td>). This kills paragraph structure for
    old-school sites using <table> layout (e.g. paulgraham.com).

    The internal XML tree has correct <p> tags — we unwrap them from <cell>
    and re-serialize. Only diverges from the standard path when layout table
    cells are actually detected; otherwise uses trafilatura.extract() directly.
    """
    doc = trafilatura.bare_extraction(
        html,
        output_format="xml",
        include_links=True,
        include_tables=True,
        include_images=True,
    )
    if not doc or doc.body is None:  # type: ignore[union-attr]  # always Document when as_dict=False
        return None

    body = doc.body  # type: ignore[union-attr]

    # Detect layout tables: cells containing many <p> elements.
    # Real data tables have short cell content; layout tables wrap entire articles.
    layout_cells = [cell for cell in body.iter("cell") if len(cell.findall("p")) >= _LAYOUT_TABLE_THRESHOLD]

    if not layout_cells:
        # No layout tables — use standard trafilatura serialization
        return trafilatura.extract(
            html, output_format="markdown", include_links=True, include_tables=True, include_images=True
        )

    # Unwrap paragraph content from layout table cells and re-serialize
    new_body = etree.Element("body")
    for cell in layout_cells:
        for child in cell:
            new_body.append(deepcopy(child))
    logger.debug(f"Unwrapped {len(layout_cells)} layout table cells for extraction")

    result = xmltotxt(new_body, include_formatting=True)
    return result if result and result.strip() else None


def _convert_with_html2text(html: str) -> str:
    converter = html2text.HTML2Text()
    converter.body_width = 0
    return converter.handle(html)


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
        markdown = await asyncio.to_thread(_convert_with_html2text, html_str)
        extraction_method = "html2text"

    if url:
        markdown = resolve_relative_urls(markdown, url)

    return markdown, extraction_method
