import asyncio
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from yapit.contracts import SynthesisJob, SynthesisParameters, SynthesisResult
from yapit.gateway.processors.tts.client import ClientProcessor


class TestClientProcessor:
    """Test ClientProcessor functionality."""

    @pytest.fixture
    def processor(self):
        """Create a client processor instance."""
        mock_settings = Mock()
        mock_settings.browser_request_timeout_seconds = 5

        mock_redis = AsyncMock()
        mock_cache = AsyncMock()

        return ClientProcessor(
            slug="kokoro-client-free",
            settings=mock_settings,
            redis=mock_redis,
            cache=mock_cache,
        )

    @pytest.fixture
    def sample_job(self):
        """Create a sample synthesis job."""
        return SynthesisJob(
            job_id=uuid.uuid4(),
            variant_hash="test_hash",
            user_id="test_user",
            synthesis_parameters=SynthesisParameters(
                model_slug="kokoro-client-free",
                voice_slug="test_voice",
                text="Test text",
                codec="opus",
            ),
        )

    def test_submit_result_success(self, processor, sample_job):
        """Test successfully submitting a result for a pending job."""
        # Start processing in background
        future = asyncio.Future()
        processor._pending_jobs[str(sample_job.job_id)] = (future, sample_job)

        # Submit result
        result = SynthesisResult(
            job_id=sample_job.job_id,
            audio=b"test_audio",
            duration_ms=1000,
        )

        success = processor.submit_result(result)

        assert success is True
        assert future.done()
        assert future.result() == result
        assert str(sample_job.job_id) not in processor._pending_jobs

    def test_submit_result_already_completed(self, processor, sample_job):
        """Test that submitting a result twice for the same job fails."""
        # Set up completed future
        future = asyncio.Future()
        future.set_result(
            SynthesisResult(
                job_id=sample_job.job_id,
                audio=b"original_audio",
                duration_ms=500,
            )
        )
        processor._pending_jobs[str(sample_job.job_id)] = (future, sample_job)

        # Try to submit another result
        new_result = SynthesisResult(
            job_id=sample_job.job_id,
            audio=b"new_audio",
            duration_ms=1000,
        )

        success = processor.submit_result(new_result)

        assert success is False
        # Original result should remain unchanged
        assert future.result().audio == b"original_audio"

    def test_get_job_exists(self, processor, sample_job):
        """Test retrieving details of a pending job."""
        # Set up pending job
        future = asyncio.Future()
        processor._pending_jobs[str(sample_job.job_id)] = (future, sample_job)

        retrieved_job = processor.get_job(str(sample_job.job_id))

        assert retrieved_job == sample_job
        assert retrieved_job.variant_hash == "test_hash"
        assert retrieved_job.user_id == "test_user"

    def test_get_job_not_found(self, processor):
        """Test that getting a non-existent job returns None."""
        job_id = str(uuid.uuid4())

        retrieved_job = processor.get_job(job_id)

        assert retrieved_job is None

    def test_get_job_completed(self, processor, sample_job):
        """Test that getting a completed job returns None."""
        # Set up completed future
        future = asyncio.Future()
        future.set_result(
            SynthesisResult(
                job_id=sample_job.job_id,
                audio=b"test_audio",
                duration_ms=1000,
            )
        )
        processor._pending_jobs[str(sample_job.job_id)] = (future, sample_job)

        retrieved_job = processor.get_job(str(sample_job.job_id))

        assert retrieved_job is None  # Job is done, so not available
