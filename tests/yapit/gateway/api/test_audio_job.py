"""Background audio jobs, driven at the HTTP API with a stub worker standing in for Kokoro.

The stub worker pulls from the real queue and hands each result to the real result consumer; the
feeder's step is the real top_up, run for every wake the result consumer pushed. Each test steps
them by hand, so the queue's order is observed exactly rather than raced.
"""

import base64
import datetime as dt
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from yapit.contracts import (
    AUDIO_JOB_WAKE,
    TTS_BILLING_STREAM,
    TTS_INFLIGHT,
    TTS_JOBS,
    TTS_PENDING,
    SynthesisJob,
    WorkerResult,
    get_queue_name,
)
from yapit.gateway.api.v1.ws import WSCursorMoved, _handle_cursor_moved
from yapit.gateway.audio_job import SLICE_SIZE, _reconcile, top_up
from yapit.gateway.auth import User, authenticate, authenticate_optional
from yapit.gateway.config import get_settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import (
    Document,
    Plan,
    PlanTier,
    SubscriptionStatus,
    TTSModel,
    UsagePeriod,
    UserSubscription,
    Voice,
)
from yapit.gateway.result_consumer import _process_result
from yapit.gateway.synthesis import request_synthesis
from yapit.queue import QueueConfig, pull_job

from .conftest import DEFAULT_TEST_USER

QUEUE = get_queue_name("kokoro")
QUEUE_CONFIG = QueueConfig(queue_name=QUEUE, jobs_key=TTS_JOBS)


@pytest.fixture
async def kokoro(session):
    model = TTSModel(slug="kokoro", name="Kokoro")
    voice = Voice(slug="af_heart", name="Heart", lang="en-us", model=model)
    session.add(model)
    session.add(voice)
    await session.commit()
    return voice


@pytest.fixture
def settings(app):
    return app.dependency_overrides[get_settings]().model_copy(update={"billing_enabled": False})


async def create_document(client, blocks: int) -> uuid.UUID:
    content = "\n\n".join(f"Paragraph {i} of the book is read aloud." for i in range(blocks))
    response = await client.post("/v1/documents/text", json={"content": content})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


async def start(client, document_id, first: int, last: int):
    return await client.post(
        f"/v1/documents/{document_id}/audio-job",
        json={
            "model": "kokoro",
            "voice": "af_heart",
            "ranges": [{"first_block": first, "last_block": last, "title": "Chapter 1"}],
        },
    )


class Pipeline:
    """The queue's consumers, stepped one result at a time."""

    def __init__(self, app, settings):
        self.redis = app.state.redis_client
        self.cache = app.state.audio_cache
        self.settings = settings
        self.synthesized: list[SynthesisJob] = []

    async def queued_jobs(self) -> list[SynthesisJob]:
        """The queue's jobs, in the order workers pull them."""
        job_ids = await self.redis.zrange(QUEUE, 0, -1)
        wrappers = [await self.redis.hget(TTS_JOBS, job_id) for job_id in job_ids]
        return [SynthesisJob.model_validate_json(json.loads(w)["job"]) for w in wrappers if w]

    async def pull(self) -> SynthesisJob | None:
        if not await self.redis.zcard(QUEUE):
            return None
        pulled = await pull_job(self.redis, QUEUE_CONFIG, timeout=1)
        return SynthesisJob.model_validate_json(pulled.raw_job) if pulled else None

    async def finish(self, job: SynthesisJob) -> None:
        """The worker's result for a job, then the feeder's step for every job it woke."""
        self.synthesized.append(job)
        await _process_result(self.redis, _result_of(job))
        await self.feed()

    async def feed(self) -> None:
        while (raw := await self.redis.rpop(AUDIO_JOB_WAKE)) is not None:
            await top_up(self.redis, self.cache, self.settings, raw.decode())

    async def run(self, max_queued_job_blocks: list[int] | None = None) -> None:
        """Work the queue until it is empty, noting how many job blocks were queued before each pull."""
        await self.feed()
        while True:
            if max_queued_job_blocks is not None:
                max_queued_job_blocks.append(len(await self.queued_jobs()))
            job = await self.pull()
            if job is None:
                return
            await self.finish(job)


def _result_of(job: SynthesisJob) -> WorkerResult:
    return WorkerResult(
        job_id=job.job_id,
        variant_hash=job.variant_hash,
        user_id=job.user_id,
        document_id=job.document_id,
        block_idx=job.block_idx,
        model_slug=job.model_slug,
        voice_slug=job.voice_slug,
        text_length=len(job.synthesis_parameters.text),
        usage_multiplier=job.usage_multiplier,
        worker_id="stub",
        processing_time_ms=1,
        queue_wait_ms=1,
        audio_base64=base64.b64encode(f"OggS {job.variant_hash}".encode()).decode(),
        duration_ms=1000,
    )


@pytest.fixture
def pipeline(app, settings):
    return Pipeline(app, settings)


@contextmanager
def signed_in_as(app, user_id: str):
    user = User(id=user_id, is_anonymous=False)
    app.dependency_overrides[authenticate] = lambda: user
    app.dependency_overrides[authenticate_optional] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides[authenticate] = lambda: DEFAULT_TEST_USER
        app.dependency_overrides[authenticate_optional] = lambda: DEFAULT_TEST_USER


async def subscribe(user_id: str, server_kokoro_characters: int | None) -> None:
    now = datetime.now(tz=dt.UTC)
    async with create_session() as session:
        plan = Plan(tier=PlanTier.basic, name="Basic", server_kokoro_characters=server_kokoro_characters)
        session.add(plan)
        await session.flush()
        subscription = UserSubscription(
            user_id=user_id,
            plan_id=plan.id,
            status=SubscriptionStatus.active,
            current_period_start=now - timedelta(days=1),
            current_period_end=now + timedelta(days=29),
        )
        session.add(subscription)
        session.add(
            UsagePeriod(
                user_id=user_id,
                period_start=subscription.current_period_start,
                period_end=subscription.current_period_end,
            )
        )
        await session.commit()


async def billed_blocks(redis) -> list[int]:
    entries = await redis.xrange(TTS_BILLING_STREAM)
    return sorted(json.loads(fields[b"data"])["block_idx"] for _, fields in entries)


async def test_a_500_block_job_never_queues_more_than_a_slice_and_caches_every_block(client, kokoro, pipeline):
    document_id = await create_document(client, 500)

    response = await start(client, document_id, 0, 499)
    assert response.status_code == 201, response.text
    assert response.json()["total_blocks"] == 500

    queued_before_each_pull: list[int] = []
    await pipeline.run(queued_before_each_pull)

    assert max(queued_before_each_pull) == SLICE_SIZE == 16
    assert len(pipeline.synthesized) == 500
    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"], job["total_blocks"]) == ("done", 500, 500)


async def test_a_block_cached_before_the_job_is_not_billed(client, kokoro, pipeline, app):
    document_id = await create_document(client, 30)
    await start(client, document_id, 0, 9)
    await pipeline.run()

    response = await start(client, document_id, 0, 19)
    assert response.json()["cached_blocks"] == 10
    await pipeline.run()

    assert await billed_blocks(app.state.redis_client) == list(range(20))


async def test_a_listener_is_pulled_before_every_job_block_queued(client, kokoro, pipeline, app, session):
    document_id = await create_document(client, 120)
    await start(client, document_id, 0, 99)
    await pipeline.feed()
    assert len(await pipeline.queued_jobs()) == 16

    await listen(app, session, document_id, block_idx=110)

    assert [job.block_idx for job in await pipeline.queued_jobs()][:2] == [110, 0]


async def test_a_block_playback_asks_for_while_its_job_block_waits_is_moved_up(client, kokoro, pipeline, app, session):
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()

    await listen(app, session, document_id, block_idx=12)

    queue_order = [job.block_idx for job in await pipeline.queued_jobs()]
    assert queue_order[0] == 12
    assert len(queue_order) == 16


async def listen(app, session, document_id: uuid.UUID, block_idx: int) -> None:
    """What the WebSocket does when playback asks for a block."""
    doc = await session.get(Document, document_id)
    voice = (await session.exec(select(Voice))).one()
    model = await session.get(TTSModel, voice.model_id)
    await request_synthesis(
        db=session,
        redis=app.state.redis_client,
        cache=app.state.audio_cache,
        user_id="listener",
        text=doc.audio_texts[block_idx],
        model=model,
        voice=voice,
        billing_enabled=False,
        document_id=document_id,
        block_idx=block_idx,
        track_for_websocket=True,
        background=False,
    )


async def test_a_second_job_is_refused_while_one_runs(client, kokoro):
    first = await create_document(client, 40)
    second = await create_document(client, 40)
    assert (await start(client, first, 0, 39)).status_code == 201

    assert (await start(client, second, 0, 39)).status_code == 409


async def test_a_job_past_the_daily_ceiling_queues_nothing_further(client, kokoro, app):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=None)
    settings = app.dependency_overrides[get_settings]().model_copy(update={"audio_job_daily_block_limit": 20})
    pipeline = Pipeline(app, settings)
    document_id = await create_document(client, 50)

    await start(client, document_id, 0, 49)
    await pipeline.run()

    assert len(pipeline.synthesized) == 20
    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("daily_limit", 20)


async def test_a_job_that_queued_its_last_block_at_the_daily_ceiling_ends_done(client, kokoro, app):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=None)
    settings = app.dependency_overrides[get_settings]().model_copy(update={"audio_job_daily_block_limit": 20})
    pipeline = Pipeline(app, settings)
    document_id = await create_document(client, 20)

    await start(client, document_id, 0, 19)
    await pipeline.run()

    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("done", 20)


async def test_a_job_whose_usage_runs_out_queues_nothing_further(client, kokoro, app, session):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=100_000)
    pipeline = Pipeline(app, app.dependency_overrides[get_settings]())
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()

    usage = (await session.exec(select(UsagePeriod))).one()
    usage.server_kokoro_characters = 100_000
    await session.commit()
    await pipeline.run()

    assert len(pipeline.synthesized) == 16
    assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["status"] == "usage_limit"


async def test_a_job_whose_voice_is_deactivated_queues_nothing_further(client, kokoro, pipeline, session):
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()

    voice = await session.get(Voice, kokoro.id)
    assert voice is not None
    voice.is_active = False
    await session.commit()
    await pipeline.run()

    assert len(pipeline.synthesized) == 16
    assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["status"] == "failed"


async def test_cancel_takes_the_jobs_waiting_blocks_off_the_queue(client, kokoro, pipeline):
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()
    in_progress = await pipeline.pull()
    assert in_progress is not None

    assert (await client.delete(f"/v1/documents/{document_id}/audio-job")).status_code == 204
    assert await pipeline.queued_jobs() == []

    await pipeline.finish(in_progress)
    await pipeline.run()
    assert await pipeline.queued_jobs() == []
    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("cancelled", 1)


async def test_two_jobs_over_the_same_blocks_synthesize_and_bill_each_block_once(client, kokoro, pipeline, app):
    document_id = await create_document(client, 10)
    await client.patch(f"/v1/documents/{document_id}", json={"is_public": True})
    await start(client, document_id, 0, 9)
    with signed_in_as(app, "second-reader"):
        await start(client, document_id, 0, 9)
    await pipeline.feed()

    await pipeline.run()

    assert len(pipeline.synthesized) == 10
    assert await billed_blocks(app.state.redis_client) == list(range(10))
    for user_id in (DEFAULT_TEST_USER.id, "second-reader"):
        with signed_in_as(app, user_id):
            assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["status"] == "done"


async def test_a_cursor_move_leaves_a_block_a_job_awaits_in_the_queue(client, kokoro, pipeline, app, session):
    document_id = await create_document(client, 30)
    await listen(app, session, document_id, block_idx=3)
    await start(client, document_id, 0, 9)
    await pipeline.feed()

    await _handle_cursor_moved(
        FakeWebSocket(),
        WSCursorMoved(document_id=document_id, cursor=20),
        User(id="listener", is_anonymous=False),
        app.state.redis_client,
    )

    assert not await app.state.redis_client.exists(TTS_PENDING.format(user_id="listener", document_id=document_id))
    assert 3 in [job.block_idx for job in await pipeline.queued_jobs()]
    await pipeline.run()
    assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["cached_blocks"] == 10


class FakeWebSocket:
    async def send_json(self, data) -> None:
        pass


async def test_a_job_whose_queued_blocks_were_lost_with_the_gateway_carries_on(client, kokoro, pipeline, app):
    redis = app.state.redis_client
    document_id = await create_document(client, 40)
    await start(client, document_id, 0, 39)
    await pipeline.feed()
    for job in await pipeline.queued_jobs():
        await redis.zrem(QUEUE, str(job.job_id))
        await redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    await _reconcile(redis, app.state.audio_cache, pipeline.settings)
    await pipeline.run()

    assert len(pipeline.synthesized) == 24
    assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["status"] == "done"
