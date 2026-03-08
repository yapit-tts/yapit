"""Defuddle extraction service.

Runs Playwright + Chromium in an isolated container. Navigates to URLs,
injects the defuddle browser bundle, and returns extracted markdown.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from loguru import logger
from pydantic import BaseModel

PROXY_URL = os.environ.get("PROXY_URL")
assert PROXY_URL, "PROXY_URL is required (e.g. http://smokescreen:4750)"

_MAX_CONCURRENT = 50
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

_browser = None
_playwright = None
_lock = asyncio.Lock()

_BUNDLE_PATH = Path("/app/defuddle_bundle.js")
_DEFUDDLE_BUNDLE: str | None = None


def _load_bundle() -> str:
    global _DEFUDDLE_BUNDLE
    if _DEFUDDLE_BUNDLE is not None:
        return _DEFUDDLE_BUNDLE
    assert _BUNDLE_PATH.exists(), f"Defuddle bundle not found at {_BUNDLE_PATH}"
    _DEFUDDLE_BUNDLE = _BUNDLE_PATH.read_text()
    logger.info(f"Loaded defuddle bundle ({len(_DEFUDDLE_BUNDLE) // 1024} KB)")
    return _DEFUDDLE_BUNDLE


async def _get_browser():
    global _browser, _playwright
    async with _lock:
        if _browser is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"],
            )
            logger.info("Chromium started")
        return _browser


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_bundle()
    await _get_browser()
    logger.info("Defuddle service ready")
    yield
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()


app = FastAPI(lifespan=lifespan)


class ExtractRequest(BaseModel):
    url: str
    timeout_ms: int = 30_000


class ExtractResponse(BaseModel):
    markdown: str
    title: str | None


@app.post("/extract")
async def extract(req: ExtractRequest, response: Response) -> ExtractResponse:
    if not _semaphore.locked():
        await _semaphore.acquire()
    else:
        logger.warning(f"At capacity ({_MAX_CONCURRENT} concurrent), rejecting {req.url}")
        response.status_code = 503
        return ExtractResponse(markdown="", title=None)

    bundle = _load_bundle()
    t0 = time.monotonic()

    try:
        browser = await _get_browser()
        context = await browser.new_context(proxy={"server": PROXY_URL})
        await context.add_init_script(bundle)
        page = await context.new_page()
        try:
            resp = await page.goto(req.url, wait_until="networkidle", timeout=req.timeout_ms)
            if resp and resp.status >= 400:
                duration_ms = int((time.monotonic() - t0) * 1000)
                logger.info(f"HTTP {resp.status} for {req.url} ({duration_ms}ms)")
                return ExtractResponse(markdown="", title=None)

            result = await page.evaluate(
                """async (url) => {
                const d = new Defuddle(document, { url, markdown: true });
                const r = await d.parseAsync();
                return { markdown: r.content || '', title: r.title || null };
            }""",
                req.url,
            )

            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(f"Extracted {req.url} in {duration_ms}ms ({len(result.get('markdown', ''))} chars)")
            return ExtractResponse(
                markdown=result.get("markdown", ""),
                title=result.get("title"),
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(f"Extraction failed for {req.url} after {duration_ms}ms: {e}")
            return ExtractResponse(markdown="", title=None)
        finally:
            await page.close()
            await context.close()
    finally:
        _semaphore.release()


@app.get("/health")
async def health():
    browser = await _get_browser()
    assert browser.is_connected(), "Chromium not connected"
    return {"status": "ok"}
