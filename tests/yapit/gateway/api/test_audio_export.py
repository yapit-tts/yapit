"""Audio export, driven at the HTTP API over real Ogg Opus blocks in the audio cache.

The expected durations are the PCM lengths each block was encoded from, so the file's length and
its chapters are checked against what went in, not against the join's own arithmetic.
"""

import io
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import av
import numpy as np
import pytest

from yapit.contracts import TTS_AUDIO_CACHE, TTS_JOBS, get_pubsub_channel, get_queue_name
from yapit.gateway.audio_export import EXPORT_TTL_S, sweep_exports
from yapit.gateway.cache import CacheConfig
from yapit.gateway.config import get_settings
from yapit.gateway.domain_models import BlockVariant, Document, TTSModel, Voice

from .conftest import DEFAULT_TEST_USER

RATE = 24_000
# Block lengths in samples, each distinct so a block dropped, doubled or reordered changes the sums
BLOCK_SAMPLES = [RATE * 2 + 123, RATE + 7, RATE * 3 + 999, RATE // 2 + 1, RATE * 2 + 50, RATE + 333]


@pytest.fixture
async def kokoro(session):
    model = TTSModel(slug="kokoro", name="Kokoro")
    voice = Voice(slug="af_heart", name="Heart", lang="en-us", model=model)
    session.add(model)
    session.add(voice)
    await session.commit()
    return voice


@pytest.fixture
async def book(client, session, kokoro, app) -> uuid.UUID:
    """A document of six blocks, all in the cache: odd blocks in Redis only, as before the persister ran."""
    content = "\n\n".join(f"Paragraph {i} of the book is read aloud." for i in range(len(BLOCK_SAMPLES)))
    response = await client.post("/v1/documents/text", json={"content": content, "title": "A Short Book"})
    assert response.status_code == 201, response.text
    document_id = uuid.UUID(response.json()["id"])
    texts = (await session.get(Document, document_id)).audio_texts
    for idx, (text, samples) in enumerate(zip(texts, BLOCK_SAMPLES)):
        variant_hash = BlockVariant.get_hash(
            text=text, model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
        )
        audio = _ogg_opus(samples, pitch=idx + 1)
        if idx % 2:
            await app.state.redis_client.set(TTS_AUDIO_CACHE.format(hash=variant_hash), audio)
        else:
            await app.state.audio_cache.store(variant_hash, audio)
    return document_id


def _ogg_opus(samples: int, pitch: int) -> bytes:
    """A block as the Kokoro worker writes it: 24 kHz mono int16 PCM as 48 kbps Ogg Opus."""
    pcm = (np.sin(np.arange(samples) * 0.03 * pitch) * 8000).astype(np.int16)
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=RATE)
        stream.bit_rate = 48_000
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            out.mux(packet)
    return buf.getvalue()


def seconds(first: int, last: int) -> float:
    return sum(BLOCK_SAMPLES[first : last + 1]) / RATE


async def export(client, document_id, ranges: list[tuple[int, int, str]], fmt: str = "m4b"):
    return await client.post(
        f"/v1/documents/{document_id}/audio-export",
        json={
            "model": "kokoro",
            "voice": "af_heart",
            "format": fmt,
            "ranges": [{"first_block": f, "last_block": last, "title": t} for f, last, t in ranges],
        },
    )


async def exported(client, app, document_id, ranges, fmt: str = "m4b") -> bytes:
    """The file an export yields, once the tab watching the document hears it is built."""
    pubsub = app.state.redis_client.pubsub()
    await pubsub.subscribe(get_pubsub_channel(DEFAULT_TEST_USER.id, document_id))
    await pubsub.get_message(timeout=1)
    state = (await export(client, document_id, ranges, fmt)).json()
    if state["status"] == "building":
        while (message := await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)) is not None:
            heard = json.loads(message["data"])
            if heard["type"] == "audio_export" and heard["key"] == state["key"]:
                state = heard
                break
    await pubsub.aclose()
    assert state["status"] == "ready", state
    response = await client.get(f"/v1/documents/{document_id}/audio-export/{state['key']}.{fmt}")
    assert response.status_code == 200, response.text
    return response.content


def probe(data: bytes) -> tuple[float, list[tuple[str, float, float]]]:
    """The file's duration in seconds as players read it, and its chapters as (title, start, end) in seconds."""
    with av.open(io.BytesIO(data), "r") as container:
        chapters = [
            (c["metadata"]["title"], float(c["start"] * c["time_base"]), float(c["end"] * c["time_base"]))
            for c in container.chapters()
        ]
        assert container.duration is not None
        return container.duration / av.time_base, chapters


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_an_export_is_the_ticked_sections_in_their_order_with_a_chapter_each(client, app, book, fmt):
    ranges = [(0, 1, "Prelude"), (4, 5, "Chapter Two"), (2, 3, "Chapter One")]

    duration, chapters = probe(await exported(client, app, book, ranges, fmt))

    assert duration == pytest.approx(seconds(0, 1) + seconds(4, 5) + seconds(2, 3), abs=0.001)
    two_starts, one_starts = seconds(0, 1), seconds(0, 1) + seconds(4, 5)
    assert [title for title, _, _ in chapters] == ["Prelude", "Chapter Two", "Chapter One"]
    assert [start for _, start, _ in chapters] == pytest.approx([0, two_starts, one_starts], abs=0.001)
    assert chapters[-1][2] == pytest.approx(duration, abs=0.001)


async def test_a_second_export_within_a_day_is_the_stored_file(client, app, book):
    first = await exported(client, app, book, [(0, 5, "Whole book")])
    stored = list(Path(app.dependency_overrides[get_settings]().audio_export_dir).iterdir())

    response = await export(client, book, [(0, 5, "Whole book")])

    assert response.json()["status"] == "ready"
    assert await exported(client, app, book, [(0, 5, "Whole book")]) == first
    assert list(Path(app.dependency_overrides[get_settings]().audio_export_dir).iterdir()) == stored


async def test_an_export_older_than_a_day_is_gone(client, app, book):
    await exported(client, app, book, [(0, 5, "Whole book")])
    key = (await export(client, book, [(0, 5, "Whole book")])).json()["key"]
    export_dir = Path(app.dependency_overrides[get_settings]().audio_export_dir)
    (path,) = export_dir.iterdir()
    a_day_ago = time.time() - EXPORT_TTL_S - 1
    os.utime(path, (a_day_ago, a_day_ago))

    response = await client.get(f"/v1/documents/{book}/audio-export/{key}.m4b")
    sweep_exports(export_dir)

    assert response.status_code == 404
    assert list(export_dir.iterdir()) == []


async def test_an_export_with_a_block_not_prepared_is_refused(client, app, book, session, kokoro):
    texts = (await session.get(Document, book)).audio_texts
    gone = BlockVariant.get_hash(
        text=texts[2], model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
    )
    await app.state.audio_cache.delete(gone)

    response = await export(client, book, [(0, 5, "Whole book")])

    assert response.status_code == 409
    assert "1 of the 6 blocks" in response.json()["detail"]


@contextmanager
def audio_cache_of(app, max_size_mb: int):
    base = app.dependency_overrides[get_settings]
    capped = base().model_copy(
        update={"audio_cache_config": CacheConfig(path="test_audio_cache", max_size_mb=max_size_mb)}
    )
    app.dependency_overrides[get_settings] = lambda: capped
    try:
        yield
    finally:
        app.dependency_overrides[get_settings] = base


async def test_a_job_whose_audio_would_not_fit_the_audio_cache_is_refused_before_any_block_is_queued(
    client, app, kokoro, session
):
    # About 3.7 hours at the estimate's speaking rate: some 80 MB of 48 kbps Opus
    content = "\n\n".join("A sentence of about fifty characters, read aloud here." * 5 for _ in range(1000))
    document_id = uuid.UUID((await client.post("/v1/documents/text", json={"content": content})).json()["id"])
    blocks = len((await session.get(Document, document_id)).audio_texts)

    with audio_cache_of(app, max_size_mb=50):
        response = await client.post(
            f"/v1/documents/{document_id}/audio-job",
            json={
                "model": "kokoro",
                "voice": "af_heart",
                "ranges": [{"first_block": 0, "last_block": blocks - 1, "title": "All"}],
            },
        )

    assert response.status_code == 422
    assert "50 MB audio cache" in response.json()["detail"]
    assert await app.state.redis_client.zcard(get_queue_name("kokoro")) == 0
    assert await app.state.redis_client.hlen(TTS_JOBS) == 0
