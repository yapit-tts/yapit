"""Website content extraction via Playwright + defuddle.

Playwright navigates to the URL (handling JS rendering, SPAs, etc.),
then defuddle's browser bundle is injected and extracts markdown from
the real browser DOM — with full computed styles for clutter detection.
"""

import asyncio
import time
from pathlib import Path

from loguru import logger

from yapit.gateway.metrics import log_event

_browser = None
_playwright = None
_lock = asyncio.Lock()
_MAX_CONCURRENT = 50
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

_DEFUDDLE_BUNDLE: str | None = None

# Resolve bundle path: Docker puts it at /app/defuddle_bundle.js,
# local dev has it in docker/defuddle/node_modules/.
_BUNDLE_PATHS = [
    Path("/app/defuddle_bundle.js"),
    Path(__file__).resolve().parents[3]
    / "docker"
    / "defuddle"
    / "node_modules"
    / "defuddle"
    / "dist"
    / "index.full.js",
]


def _load_bundle() -> str:
    global _DEFUDDLE_BUNDLE
    if _DEFUDDLE_BUNDLE is not None:
        return _DEFUDDLE_BUNDLE
    for path in _BUNDLE_PATHS:
        if path.exists():
            _DEFUDDLE_BUNDLE = path.read_text()
            logger.info(f"Loaded defuddle bundle from {path} ({len(_DEFUDDLE_BUNDLE) // 1024} KB)")
            return _DEFUDDLE_BUNDLE
    raise RuntimeError(f"Defuddle bundle not found. Searched: {[str(p) for p in _BUNDLE_PATHS]}")


async def _get_browser():
    global _browser, _playwright
    async with _lock:
        if _browser is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            logger.info("Playwright browser started")
        return _browser


async def extract_website(url: str, timeout_ms: int = 30_000) -> tuple[str, str | None]:
    """Extract markdown from a URL via Playwright + defuddle.

    Returns (markdown, title). Markdown is empty string if extraction fails.
    """
    if _semaphore.locked():
        logger.warning(f"Playwright semaphore full ({_MAX_CONCURRENT} concurrent), queuing {url}")

    bundle = _load_bundle()
    t0 = time.monotonic()

    async with _semaphore:
        browser = await _get_browser()
        context = await browser.new_context(proxy={"server": "http://smokescreen:4750"})
        await context.add_init_script(bundle)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            result = await page.evaluate(
                """async (url) => {
                const d = new Defuddle(document, { url, markdown: true });
                const r = await d.parseAsync();
                return { markdown: r.content || '', title: r.title || null };
            }""",
                url,
            )

            markdown = result.get("markdown", "")
            title = result.get("title")
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(f"Extracted {url} in {duration_ms}ms ({len(markdown)} chars)")
            await log_event("website_extraction", data={"url": url, "chars": len(markdown), "duration_ms": duration_ms})
            return markdown, title

        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(f"Playwright extraction failed for {url} after {duration_ms}ms: {e}")
            await log_event("website_extraction_error", data={"url": url, "error": str(e), "duration_ms": duration_ms})
            return "", None
        finally:
            await page.close()
            await context.close()
