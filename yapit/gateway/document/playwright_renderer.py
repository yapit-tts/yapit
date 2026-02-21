import asyncio
import time

from loguru import logger

from yapit.gateway.metrics import log_event

_browser = None
_playwright = None
_lock = asyncio.Lock()
_semaphore = asyncio.Semaphore(100)


async def _get_browser():
    """Get or create the shared browser instance (lazy-loaded)."""
    global _browser, _playwright
    async with _lock:
        if _browser is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            logger.info("Playwright browser instance started")
        return _browser


async def render_with_js(url: str, timeout_ms: int = 30000) -> str:
    """Render a page with JavaScript execution.

    Uses browser pooling (single browser, new page per request).
    Semaphore limits concurrent renders to bound memory usage.
    All requests route through Smokescreen proxy to prevent SSRF.

    Args:
        url: URL to render
        timeout_ms: Navigation timeout in milliseconds

    Returns:
        Rendered HTML content
    """
    if _semaphore.locked():
        logger.warning(f"Playwright semaphore full (100 concurrent), queuing render for {url}")

    async with _semaphore:
        browser = await _get_browser()
        context = await browser.new_context(proxy={"server": "http://smokescreen:4750"})
        page = await context.new_page()
        start = time.monotonic()
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            content = await page.content()
            duration_ms = int((time.monotonic() - start) * 1000)
            asyncio.create_task(log_event("playwright_fetch", duration_ms=duration_ms))
            return content
        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            asyncio.create_task(log_event("playwright_fetch", duration_ms=duration_ms, data={"error": str(e)}))
            raise
        finally:
            await page.close()
            await context.close()
