import httpx
import pytest
from fastapi import HTTPException

from yapit.gateway.document import defuddle_client

REFUSAL = "This site's robots.txt does not allow yapit to fetch this page"


@pytest.fixture
def extraction_service(monkeypatch):
    """The extraction service, refusing every URL the way it refuses one robots.txt disallows."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": REFUSAL})

    client = httpx.AsyncClient(base_url="http://defuddle", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(defuddle_client, "_client", client)


@pytest.mark.asyncio
async def test_a_refused_extraction_reaches_the_api_as_its_reason(extraction_service):
    with pytest.raises(HTTPException) as exc_info:
        await defuddle_client.extract_website("https://example.com/private")
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == REFUSAL


@pytest.mark.asyncio
async def test_a_refused_robots_check_reaches_the_api_as_its_reason(extraction_service):
    with pytest.raises(HTTPException) as exc_info:
        await defuddle_client.assert_robots_allow("https://example.com/private")
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == REFUSAL
