"""Gemini Batch API integration for document extraction."""

import base64
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit.gateway.metrics import log_event


class BatchPageRequest(TypedDict):
    page_idx: int
    page_pdf_bytes: bytes
    prompt: str


BATCH_JOB_TTL_SECONDS = 48 * 60 * 60  # 48 hours
ACTIVE_BATCH_JOBS_KEY = "active_batch_jobs"


class BatchJobStatus(StrEnum):
    PREPARING = "PREPARING"  # YOLO + batch file upload in progress (pre-submission)
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class BatchJobInfo(BaseModel):
    job_name: str | None = None  # None during PREPARING (no Gemini batch yet)
    user_id: str
    content_hash: str
    total_pages: int
    submitted_at: str
    status: BatchJobStatus
    title: str | None
    content_type: str
    file_size: int
    pages_requested: list[int]
    figure_urls_by_page: dict[int, list[str]]
    poll_count: int = 0
    document_id: str | None = None
    error: str | None = None


def _batch_job_key(content_hash: str) -> str:
    return f"batch:{content_hash}"


async def get_batch_job(redis: Redis, content_hash: str) -> BatchJobInfo | None:
    key = _batch_job_key(content_hash)
    data = await redis.get(key)
    if data:
        return BatchJobInfo.model_validate_json(data)
    return None


async def save_batch_job(redis: Redis, job: BatchJobInfo) -> None:
    key = _batch_job_key(job.content_hash)
    await redis.set(key, job.model_dump_json(), ex=BATCH_JOB_TTL_SECONDS)


async def _add_to_active_set(redis: Redis, content_hash: str) -> None:
    await redis.sadd(ACTIVE_BATCH_JOBS_KEY, content_hash)


async def _remove_from_active_set(redis: Redis, content_hash: str) -> None:
    await redis.srem(ACTIVE_BATCH_JOBS_KEY, content_hash)


async def delete_batch_job(redis: Redis, content_hash: str) -> None:
    key = _batch_job_key(content_hash)
    await redis.delete(key)
    await _remove_from_active_set(redis, content_hash)


async def list_pending_batch_jobs(redis: Redis) -> list[BatchJobInfo]:
    """List all batch jobs that need polling."""
    content_hashes = await redis.smembers(ACTIVE_BATCH_JOBS_KEY)
    jobs = []
    for ch in content_hashes:
        content_hash = ch.decode() if isinstance(ch, bytes) else ch
        job = await get_batch_job(redis, content_hash)
        if job and job.status in (BatchJobStatus.PENDING, BatchJobStatus.RUNNING):
            jobs.append(job)
        elif job is None:
            # Stale entry — job expired via TTL but Set wasn't cleaned
            await _remove_from_active_set(redis, content_hash)
    return jobs


def _map_gemini_state_to_status(state_name: str) -> BatchJobStatus:
    mapping = {
        "JOB_STATE_PENDING": BatchJobStatus.PENDING,
        "JOB_STATE_RUNNING": BatchJobStatus.RUNNING,
        "JOB_STATE_SUCCEEDED": BatchJobStatus.SUCCEEDED,
        "JOB_STATE_FAILED": BatchJobStatus.FAILED,
        "JOB_STATE_CANCELLED": BatchJobStatus.CANCELLED,
        "JOB_STATE_EXPIRED": BatchJobStatus.EXPIRED,
    }
    return mapping.get(state_name, BatchJobStatus.FAILED)


def _build_jsonl_line(page_idx: int, page_pdf_bytes: bytes, prompt: str) -> str:
    pdf_base64 = base64.b64encode(page_pdf_bytes).decode("ascii")
    request_obj = {
        "key": f"page_{page_idx}",
        "request": {
            "contents": [
                {"parts": [{"inline_data": {"mime_type": "application/pdf", "data": pdf_base64}}]},
                {"parts": [{"text": prompt}]},
            ]
        },
    }
    return json.dumps(request_obj, separators=(",", ":"))


def _write_batch_jsonl(page_requests: list[BatchPageRequest], output_path: Path) -> None:
    with open(output_path, "w") as f:
        for req in page_requests:
            line = _build_jsonl_line(req["page_idx"], req["page_pdf_bytes"], req["prompt"])
            f.write(line + "\n")


async def submit_batch_job(
    client: genai.Client,
    redis: Redis,
    user_id: str,
    content_hash: str,
    model: str,
    page_requests: list[BatchPageRequest],
    title: str | None,
    content_type: str,
    file_size: int,
    pages_requested: list[int],
    figure_urls_by_page: dict[int, list[str]],
) -> BatchJobInfo:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        jsonl_path = Path(f.name)

    _write_batch_jsonl(page_requests, jsonl_path)
    jsonl_size = jsonl_path.stat().st_size
    logger.info(f"Batch JSONL: {jsonl_size} bytes, {len(page_requests)} requests")

    try:
        uploaded_file = await client.aio.files.upload(
            file=str(jsonl_path),
            config=types.UploadFileConfig(
                display_name=f"yapit-batch-{content_hash[:16]}",
                mime_type="application/jsonl",
            ),
        )
        assert uploaded_file.name is not None
        logger.info(f"Batch file uploaded: {uploaded_file.name}")

        batch_job = await client.aio.batches.create(
            model=model,
            src=uploaded_file.name,
            config=types.CreateBatchJobConfigDict(display_name=f"yapit:{content_hash[:16]}"),
        )
    finally:
        jsonl_path.unlink(missing_ok=True)

    assert batch_job.name is not None
    assert batch_job.state is not None

    job_info = BatchJobInfo(
        job_name=batch_job.name,
        user_id=user_id,
        content_hash=content_hash,
        total_pages=len(page_requests),
        submitted_at=datetime.now(UTC).isoformat(),
        status=_map_gemini_state_to_status(batch_job.state.name),
        title=title,
        content_type=content_type,
        file_size=file_size,
        pages_requested=pages_requested,
        figure_urls_by_page=figure_urls_by_page,
    )

    await save_batch_job(redis, job_info)
    await _add_to_active_set(redis, content_hash)

    logger.info(f"Batch job submitted: {job_info.job_name} ({job_info.total_pages} pages)")
    await log_event(
        "batch_job_submitted",
        user_id=user_id,
        data={
            "job_name": job_info.job_name,
            "content_hash": content_hash,
            "total_pages": job_info.total_pages,
            "jsonl_size": jsonl_size,
        },
    )

    return job_info


async def poll_batch_job(
    client: genai.Client,
    redis: Redis,
    job: BatchJobInfo,
) -> tuple[BatchJobInfo, types.BatchJob]:
    """Returns (updated job info, raw Gemini BatchJob) so callers can access
    dest.file_name without re-fetching.
    """
    old_status = job.status
    assert job.job_name is not None, "Cannot poll a job without a Gemini batch name"
    batch_job = await client.aio.batches.get(name=job.job_name)

    assert batch_job.state is not None
    job.status = _map_gemini_state_to_status(batch_job.state.name)
    job.poll_count += 1

    await save_batch_job(redis, job)

    # Remove from active set when no longer pollable
    if job.status not in (BatchJobStatus.PENDING, BatchJobStatus.RUNNING):
        await _remove_from_active_set(redis, job.content_hash)

    if job.status != old_status:
        logger.info(f"Batch job {job.job_name}: {old_status} → {job.status} (poll #{job.poll_count})")

    return job, batch_job


@dataclass
class BatchResult:
    key: str | None
    response: types.GenerateContentResponse | None
    error: str | None


async def get_batch_results(
    client: genai.Client,
    batch_job: types.BatchJob,
) -> list[BatchResult]:
    """Download and parse results from a completed file-based batch job.

    File-based jobs store results in a JSONL file (batch_job.dest.file_name),
    not in inlined_responses.
    """
    assert batch_job.dest is not None
    assert batch_job.dest.file_name is not None, "File-based batch job should have dest.file_name on completion"

    result_bytes = await client.aio.files.download(
        file=batch_job.dest.file_name,
    )
    result_text = result_bytes.decode("utf-8")

    results: list[BatchResult] = []
    for line in result_text.strip().split("\n"):
        if not line:
            continue
        entry = json.loads(line)
        key = entry.get("key")
        if "response" in entry:
            response = types.GenerateContentResponse.model_validate(entry["response"])
            results.append(BatchResult(key=key, response=response, error=None))
        else:
            error_msg = str(entry.get("error") or entry.get("status") or "Unknown error")
            results.append(BatchResult(key=key, response=None, error=error_msg))

    return results
