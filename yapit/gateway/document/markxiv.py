"""markxiv integration for arXiv paper extraction."""

import re

import httpx
from fastapi import HTTPException, status
from loguru import logger

from yapit.gateway.metrics import log_event

ARXIV_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:www\.)?arxiv\.org/abs/([\d.]+v?\d*)"), "abs"),
    (re.compile(r"(?:www\.)?arxiv\.org/pdf/([\d.]+v?\d*)"), "pdf"),
    (re.compile(r"(?:www\.)?alphaxiv\.org/abs/([\d.]+v?\d*)"), "abs"),
    (re.compile(r"(?:www\.)?alphaxiv\.org/pdf/([\d.]+v?\d*)"), "pdf"),
    (re.compile(r"ar5iv\.labs\.google\.com/abs/([\d.]+v?\d*)"), "abs"),
]

_HEADER_ANCHOR_PATTERN = re.compile(r"^(#+\s+.+?)\s*\{#[^}]+\}\s*$", re.MULTILINE)
_CITATION_PATTERN = re.compile(r"\s*\[@[^\]]+\]")  # [@author_year] or [@a; @b; @c]
_REFERENCE_ATTR_PATTERN = re.compile(r'\{reference-type="[^"]*"\s+reference="[^"]*"\}')
_ORPHAN_LABEL_REF_PATTERN = re.compile(
    r"\s*\[(?:fig|tab|sec|eq|alg|lst|thm|lem|def|prop|cor|rem|ex|app):[^\]]+\]", re.IGNORECASE
)


def detect_arxiv_url(url: str) -> tuple[str, str] | None:
    """Detect if URL is an arXiv paper URL. Returns (arxiv_id, url_type) or None."""
    for pattern, url_type in ARXIV_PATTERNS:
        if match := pattern.search(url):
            return match.group(1), url_type
    return None


async def fetch_from_markxiv(markxiv_url: str, arxiv_id: str) -> str:
    """Fetch markdown from markxiv service."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(f"{markxiv_url}/abs/{arxiv_id}")
    except httpx.TimeoutException:
        await log_event("markxiv_error", data={"arxiv_id": arxiv_id, "error": "timeout"})
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="arXiv paper extraction timed out. This can happen with large papers. Please try again.",
        )
    except httpx.RequestError as e:
        await log_event("markxiv_error", data={"arxiv_id": arxiv_id, "error": "connection", "detail": str(e)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to paper extraction service. Please try again in a few seconds.",
        )

    if response.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found on arXiv")
    if response.status_code == 422:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Paper has no source available and PDF extraction failed",
        )
    if response.status_code == 502:
        await log_event("markxiv_error", data={"arxiv_id": arxiv_id, "error": "arxiv_unreachable"})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach arXiv servers. This is usually temporary — please try again in a few seconds.",
        )
    if not response.is_success:
        await log_event(
            "markxiv_error", data={"arxiv_id": arxiv_id, "error": "conversion", "status": response.status_code}
        )
        logger.error(f"markxiv error for {arxiv_id}: {response.status_code} {response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Paper conversion failed. If this persists, please report at https://github.com/yapit-tts/yapit/issues",
        )

    return cleanup_markxiv_markdown(response.text)


def cleanup_markxiv_markdown(md: str) -> str:
    """Clean up pandoc-generated markdown from markxiv for TTS readability."""
    md = _HEADER_ANCHOR_PATTERN.sub(r"\1", md)
    md = _CITATION_PATTERN.sub("", md)
    md = _REFERENCE_ATTR_PATTERN.sub("", md)
    md = _ORPHAN_LABEL_REF_PATTERN.sub("", md)
    return md
