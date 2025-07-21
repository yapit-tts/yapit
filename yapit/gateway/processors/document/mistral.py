import asyncio
import base64
import json
import logging
import pprint
import time
from typing import Literal

from mistralai import Mistral, OCRResponse
from pydantic import BaseModel

from yapit.gateway.config import Settings
from yapit.gateway.processors.document.base import (
    BaseDocumentProcessor,
    DocumentExtractionResult,
    ExtractedPage,
)

log = logging.getLogger(__name__)

# TODO if we have the content already, is it better to pass the url (to save bandwidth) or the content (to not rely on external URLs, stability)?

type URLType = Literal["image_url", "document_url"]


class OCRRequest(BaseModel):
    id: str
    data_url: str  # Base64 encoded data URL or URL to the document/image
    url_type: URLType
    pages: list[int] | None = None  # 1-indexed pages


class MistralOCRProcessor(BaseDocumentProcessor):
    IMAGE_MIME_TYPES = {
        "image/*",
    }
    DOCUMENT_MIME_TYPES = {
        "application/pdf",
        "application/vnd.oasis.opendocument.text",  # ODT
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # PPTX
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    }

    def __init__(self, slug: str, settings: Settings, model: str):
        super().__init__(slug, settings)

        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY is required for Mistral OCR processor")

        self._client = Mistral(api_key=settings.mistral_api_key)
        self._model = model

    @property
    def _processor_supported_mime_types(self) -> set[str]:
        return self.IMAGE_MIME_TYPES | self.DOCUMENT_MIME_TYPES

    @property
    def max_pages(self) -> int:
        return 1000

    @property
    def max_file_size(self) -> int:  # TODO use this to validate early
        return 50 * 1024 * 1024

    async def _extract(
        self,
        content_type: str,
        url: str | None = None,
        content: bytes | None = None,
        pages: list[int] | None = None,
    ) -> DocumentExtractionResult:
        response = await asyncio.to_thread(
            _single_ocr,
            OCRRequest(
                id="_",  # not necessary for single requests
                data_url=url if url else f"data:{content_type};base64,{base64.b64encode(content).decode('utf-8')}",
                url_type=_get_url_type(content_type),
                pages=[p - 1 for p in pages] if pages else None,  # API uses 0-indexed
            ),
            model=self._model,
            client=self._client,
        )
        return DocumentExtractionResult(
            pages={page.index + 1: ExtractedPage(markdown=page.markdown) for page in response.pages},  # 1-indexed pages
            extraction_method=self.processor_slug,
        )


def _get_url_type(content_type: str) -> URLType:
    return "image_url" if content_type.lower().startswith("image/") else "document_url"


def _single_ocr(request: OCRRequest, model: str, client: Mistral) -> OCRResponse:
    request_params = {
        "model": model,
        "document": {
            "type": request.url_type,
            request.url_type: request.data_url,
        },
        "include_image_base64": True,
        "pages": request.pages,
    }
    log.info(f"Calling Mistral OCR API with params:\n{pprint.pformat(request_params)}")
    return client.ocr.process(**request_params)


# TODO actually support batch processing vs. priority requests


def _batch_ocr(batch: list[OCRRequest], client: Mistral, model: str) -> dict[str, OCRResponse]:
    """OCR a list of data URLs using Mistral's batch API.

    Returns:
        Dict mapping request IDs to OCRResponse objects.
    """
    batch_requests = []
    for request in batch:
        batch_requests.append(
            {
                "custom_id": f"{request.id}",
                "body": {
                    "document": {"type": request.url_type, request.url_type: request.data_url},
                },
                "include_image_base64": True,
            }
        )
    batch_content = "\n".join(json.dumps(req) for req in batch_requests)  # JSONL
    batch_file = client.files.upload(
        file={"file_name": "batch.jsonl", "content": batch_content.encode()}, purpose="batch"
    )

    log.info(
        f"Calling Mistral OCR API with batch request {batch_file.id} (length {len(batch_requests)}):\n{pprint.pformat(batch_requests)}"
    )
    job = client.batch.jobs.create(input_files=[batch_file.id], model=model, endpoint="/v1/ocr")
    while job.status in ["QUEUED", "RUNNING"]:  # TODO split into separate function?
        time.sleep(1)  # TODO backoff?
        job = client.batch.jobs.get(job_id=job.id)

    output = client.files.download(file_id=job.output_file)
    return {
        result["custom_id"]: OCRResponse.model_validate_json(result["response"]["body"])
        for result in (json.loads(line) for line in output.content.decode().strip().split("\n"))
    }
