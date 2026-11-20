"""Background audio jobs, driven at the HTTP API with a stub worker standing in for Kokoro.

The stub worker pulls from the real queue and hands each result to the real result consumer; the
feeder's step is the real feed_job, run for every wake the result consumer pushed. Each test steps
them by hand, so the queue's order is observed exactly rather than raced.
"""

import asyncio
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
    TTS_AUDIO_CACHE,
    TTS_BILLING_STREAM,
    TTS_INFLIGHT,
    TTS_JOBS,
    TTS_PENDING,
    SynthesisJob,
    WorkerResult,
    get_pubsub_channel,
    get_queue_name,
)
from yapit.gateway.api.v1.ws import WSCursorMoved, WSSynthesizeRequest, _handle_cursor_moved, _handle_synthesize
from yapit.gateway.audio_job import SLICE_SIZE, _reconcile, feed_job, run_audio_job_feeder
from yapit.gateway.auth import User, authenticate, authenticate_optional
from yapit.gateway.config import get_settings
from yapit.gateway.db import create_session
from yapit.gateway.domain_models import (
    Plan,
    PlanTier,
    SubscriptionStatus,
    TTSModel,
    UsagePeriod,
    UserSubscription,
    Voice,
)
from yapit.gateway.result_consumer import _process_result
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

    async def finish(self, job: SynthesisJob, error: str | None = None) -> None:
        """The worker's result for a job, then the feeder's step for every job it woke."""
        self.synthesized.append(job)
        await _process_result(self.redis, _result_of(job, error))
        await self.feed()

    async def feed(self) -> None:
        while (raw := await self.redis.rpop(AUDIO_JOB_WAKE)) is not None:
            await feed_job(self.redis, self.cache, self.settings, raw.decode())

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


def _result_of(job: SynthesisJob, error: str | None) -> WorkerResult:
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
        audio_base64=None if error else base64.b64encode(f"OggS {job.variant_hash}".encode()).decode(),
        duration_ms=None if error else 1000,
        error=error,
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


async def test_a_listener_is_pulled_before_every_job_block_queued(client, kokoro, pipeline, app, settings):
    document_id = await create_document(client, 120)
    await start(client, document_id, 0, 99)
    await pipeline.feed()
    assert len(await pipeline.queued_jobs()) == 16

    await listen(app, settings, document_id, block_idx=110)

    assert [job.block_idx for job in await pipeline.queued_jobs()][:2] == [110, 0]


async def test_a_block_playback_asks_for_while_its_job_block_waits_is_moved_up(client, kokoro, pipeline, app, settings):
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()

    await listen(app, settings, document_id, block_idx=12)

    queue_order = [job.block_idx for job in await pipeline.queued_jobs()]
    assert queue_order[0] == 12
    assert len(queue_order) == 16


class FakeWebSocket:
    async def send_json(self, data) -> None:
        pass


async def listen(app, settings, document_id: uuid.UUID, block_idx: int) -> None:
    """Playback asking for a block, as the WebSocket's synthesize message does."""
    await _handle_synthesize(
        FakeWebSocket(),
        WSSynthesizeRequest(document_id=document_id, block_indices=[block_idx], model="kokoro", voice="af_heart"),
        DEFAULT_TEST_USER,
        app.state.redis_client,
        app.state.audio_cache,
        settings,
    )


async def test_a_block_a_worker_already_took_is_not_queued_again_when_playback_asks_for_it(
    client, kokoro, pipeline, app, settings
):
    document_id = await create_document(client, 30)
    await start(client, document_id, 0, 29)
    await pipeline.feed()
    taken = await pipeline.pull()
    assert taken is not None

    await listen(app, settings, document_id, block_idx=taken.block_idx)

    assert taken.block_idx not in [job.block_idx for job in await pipeline.queued_jobs()]
    await pipeline.finish(taken)
    await pipeline.run()
    assert sorted(job.block_idx for job in pipeline.synthesized) == list(range(30))


async def test_a_block_gone_from_the_cache_since_it_was_synthesized_is_synthesized_again(
    client, kokoro, pipeline, app, settings
):
    redis = app.state.redis_client
    document_id = await create_document(client, 5)
    await listen(app, settings, document_id, block_idx=0)
    await pipeline.run()
    variant_hash = pipeline.synthesized[0].variant_hash
    await redis.delete(TTS_AUDIO_CACHE.format(hash=variant_hash))

    await listen(app, settings, document_id, block_idx=0)
    await pipeline.run()

    assert await redis.exists(TTS_AUDIO_CACHE.format(hash=variant_hash))
    assert await billed_blocks(redis) == [0, 0]


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


async def test_a_job_at_the_daily_ceiling_still_ends_done_over_blocks_already_cached(client, kokoro, app):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=None)
    settings = app.dependency_overrides[get_settings]().model_copy(update={"audio_job_daily_block_limit": 20})
    pipeline = Pipeline(app, settings)
    document_id = await create_document(client, 30)
    for block_idx in range(20, 30):
        await listen(app, settings, document_id, block_idx)
    await pipeline.run()

    await start(client, document_id, 0, 29)
    await pipeline.run()

    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("done", 30)


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


async def test_cancel_leaves_a_block_a_listener_waits_on(client, kokoro, pipeline, app, settings):
    document_id = await create_document(client, 50)
    await start(client, document_id, 0, 49)
    await pipeline.feed()
    await listen(app, settings, document_id, block_idx=7)

    await client.delete(f"/v1/documents/{document_id}/audio-job")

    assert [job.block_idx for job in await pipeline.queued_jobs()] == [7]


async def test_cancel_leaves_the_blocks_another_users_job_awaits(client, kokoro, pipeline, app):
    document_id = await create_document(client, 10)
    await client.patch(f"/v1/documents/{document_id}", json={"is_public": True})
    await start(client, document_id, 0, 9)
    with signed_in_as(app, "second-reader"):
        await start(client, document_id, 0, 9)
    await pipeline.feed()

    await client.delete(f"/v1/documents/{document_id}/audio-job")
    await pipeline.run()

    assert len(pipeline.synthesized) == 10
    with signed_in_as(app, "second-reader"):
        job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("done", 10)


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


async def test_a_cursor_move_leaves_a_block_a_job_awaits_in_the_queue(client, kokoro, pipeline, app, settings):
    document_id = await create_document(client, 30)
    await listen(app, settings, document_id, block_idx=3)
    await start(client, document_id, 0, 9)
    await pipeline.feed()

    await _handle_cursor_moved(
        FakeWebSocket(),
        WSCursorMoved(document_id=document_id, cursor=20),
        DEFAULT_TEST_USER,
        app.state.redis_client,
    )

    pending = TTS_PENDING.format(user_id=DEFAULT_TEST_USER.id, document_id=document_id)
    assert not await app.state.redis_client.exists(pending)
    assert 3 in [job.block_idx for job in await pipeline.queued_jobs()]
    await pipeline.run()
    assert (await client.get(f"/v1/documents/{document_id}/audio-job")).json()["cached_blocks"] == 10


async def test_a_job_whose_queued_blocks_were_lost_with_the_gateway_queues_them_again(client, kokoro, pipeline, app):
    redis = app.state.redis_client
    document_id = await create_document(client, 40)
    await start(client, document_id, 0, 39)
    await pipeline.feed()
    for job in await pipeline.queued_jobs():
        await redis.zrem(QUEUE, str(job.job_id))
        await redis.hdel(TTS_JOBS, str(job.job_id))
        await redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    await _reconcile(redis, app.state.audio_cache, pipeline.settings)
    await pipeline.run()

    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("done", 40)


async def test_a_job_block_that_outwaits_its_marker_keeps_its_place_in_the_slice(client, kokoro, pipeline, app):
    redis = app.state.redis_client
    document_id = await create_document(client, 40)
    await start(client, document_id, 0, 39)
    await pipeline.feed()
    queued = await pipeline.queued_jobs()
    for job in queued:
        await redis.delete(TTS_INFLIGHT.format(hash=job.variant_hash))

    await _reconcile(redis, app.state.audio_cache, pipeline.settings)

    assert await pipeline.queued_jobs() == queued
    for job in queued:
        assert await redis.get(TTS_INFLIGHT.format(hash=job.variant_hash)) == str(job.job_id).encode()


async def test_a_block_the_worker_fails_does_not_stall_the_job(client, kokoro, pipeline):
    document_id = await create_document(client, 30)
    await start(client, document_id, 0, 29)
    await pipeline.feed()
    failing = await pipeline.pull()
    assert failing is not None

    await pipeline.finish(failing, error="Synthesis failed")
    await pipeline.run()

    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()
    assert (job["status"], job["cached_blocks"]) == ("done", 29)


async def test_the_feeder_queues_a_new_jobs_first_slice(client, kokoro, app, settings):
    document_id = await create_document(client, 30)
    feeder = asyncio.create_task(run_audio_job_feeder(app.state.redis_client, app.state.audio_cache, settings))
    try:
        await start(client, document_id, 0, 29)
        pulled = await pull_job(app.state.redis_client, QUEUE_CONFIG, timeout=10)
    finally:
        feeder.cancel()
        await asyncio.gather(feeder, return_exceptions=True)

    assert pulled is not None
    assert SynthesisJob.model_validate_json(pulled.raw_job).block_idx == 0


async def estimate(client, document_id) -> dict:
    response = await client.get(
        f"/v1/documents/{document_id}/audio-job/estimate", params={"model": "kokoro", "voice": "af_heart"}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_estimate_counts_the_billed_characters_of_uncached_blocks_only(
    client, kokoro, pipeline, app, settings, session
):
    model = await session.get(TTSModel, kokoro.model_id)
    assert model is not None
    model.usage_multiplier = 2.0
    await session.commit()
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=100_000)
    document_id = await create_document(client, 12)
    await listen(app, settings, document_id, block_idx=10)
    await pipeline.run()
    # As the cache persister leaves it past the hot cache's lifetime: on disk only
    variant_hash = pipeline.synthesized[0].variant_hash
    await app.state.audio_cache.store(variant_hash, b"OggS")
    await app.state.redis_client.delete(TTS_AUDIO_CACHE.format(hash=variant_hash))

    result = await estimate(client, document_id)

    # "Paragraph 1 of the book is read aloud." is 38 characters, "Paragraph 11 ..." 39, each billed twice
    assert result["uncached_characters"] == [76] * 10 + [0, 78]
    assert (result["available_characters"], result["daily_blocks_left"]) == (100_000, None)


async def test_the_estimate_shows_no_server_kokoro_on_the_free_plan(client, kokoro):
    document_id = await create_document(client, 3)

    result = await estimate(client, document_id)

    assert (result["plan_includes_voice"], result["available_characters"]) == (False, 0)


async def test_the_estimate_tells_a_used_up_quota_from_a_plan_without_server_kokoro(client, kokoro, session):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=1_000)
    usage = (await session.exec(select(UsagePeriod))).one()
    usage.server_kokoro_characters = 1_000
    await session.commit()
    document_id = await create_document(client, 3)

    result = await estimate(client, document_id)

    assert (result["plan_includes_voice"], result["available_characters"]) == (True, 0)


async def test_the_estimate_shows_the_daily_ceiling_left_on_an_unlimited_plan(client, kokoro, app):
    await subscribe(DEFAULT_TEST_USER.id, server_kokoro_characters=None)
    base = app.dependency_overrides[get_settings]
    settings = base().model_copy(update={"audio_job_daily_block_limit": 20})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        document_id = await create_document(client, 30)
        await start(client, document_id, 0, 4)
        await Pipeline(app, settings).run()

        result = await estimate(client, document_id)
    finally:
        app.dependency_overrides[get_settings] = base

    assert (result["available_characters"], result["daily_blocks_left"]) == (None, 15)


async def test_the_estimate_names_the_document_of_a_running_job_until_it_ends(client, kokoro):
    running = await create_document(client, 20)
    other = await create_document(client, 20)
    await start(client, running, 0, 19)

    assert (await estimate(client, other))["running_job_document_id"] == str(running)

    await client.delete(f"/v1/documents/{running}/audio-job")
    assert (await estimate(client, other))["running_job_document_id"] is None


async def test_a_running_jobs_pending_blocks_are_those_not_yet_cached(client, kokoro, pipeline):
    document_id = await create_document(client, 40)
    await start(client, document_id, 5, 24)
    await pipeline.feed()
    first = await pipeline.pull()
    assert first is not None
    await pipeline.finish(first)

    job = (await client.get(f"/v1/documents/{document_id}/audio-job")).json()

    assert job["pending_blocks"] == [i for i in range(5, 25) if i != first.block_idx]


async def test_a_document_without_a_job_answers_none(client, kokoro):
    document_id = await create_document(client, 3)

    response = await client.get(f"/v1/documents/{document_id}/audio-job")

    assert (response.status_code, response.json()) == (200, None)


async def heard(pubsub) -> list[dict]:
    """The job states a tab watching the channel was sent, in order."""
    messages = []
    while (message := await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)) is not None:
        messages.append(json.loads(message["data"]))
    return [m["job"] for m in messages if m["type"] == "audio_job"]


async def watching(app, document_id):
    pubsub = app.state.redis_client.pubsub()
    await pubsub.subscribe(get_pubsub_channel(DEFAULT_TEST_USER.id, document_id))
    await pubsub.get_message(timeout=1)  # the subscribe confirmation
    return pubsub


async def test_a_tab_on_the_document_hears_each_block_the_job_caches_and_its_end(client, kokoro, pipeline, app):
    document_id = await create_document(client, 10)
    pubsub = await watching(app, document_id)
    await start(client, document_id, 0, 2)

    await pipeline.run()

    states = await heard(pubsub)
    assert [(s["status"], s["cached_blocks"]) for s in states][-3:] == [("running", 1), ("running", 2), ("done", 3)]
    await pubsub.aclose()


async def test_a_tab_on_the_document_hears_its_job_cancelled(client, kokoro, pipeline, app):
    document_id = await create_document(client, 40)
    await start(client, document_id, 0, 39)
    await pipeline.feed()
    pubsub = await watching(app, document_id)

    await client.delete(f"/v1/documents/{document_id}/audio-job")

    assert [s["status"] for s in await heard(pubsub)] == ["cancelled"]
    await pubsub.aclose()


async def test_a_tab_on_another_document_hears_nothing_of_the_job(client, kokoro, pipeline, app):
    document_id = await create_document(client, 5)
    other = await create_document(client, 5)
    pubsub = await watching(app, other)
    await start(client, document_id, 0, 4)

    await pipeline.run()

    assert await heard(pubsub) == []
    await pubsub.aclose()
