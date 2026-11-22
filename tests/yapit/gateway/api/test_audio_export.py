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

from yapit.contracts import TTS_AUDIO_CACHE, TTS_JOBS, WorkerResult, get_pubsub_channel, get_queue_name
from yapit.gateway import audio_export
from yapit.gateway.audio_export import EXPORT_TTL_S, sweep_exports
from yapit.gateway.cache import CacheConfig
from yapit.gateway.config import get_settings
from yapit.gateway.domain_models import BlockVariant, Document, TTSModel, Voice
from yapit.gateway.result_consumer import _process_result

from .conftest import DEFAULT_TEST_USER

RATE = 24_000
# Block lengths in samples, each distinct so a block dropped, doubled or reordered changes the sums
BLOCK_SAMPLES = [RATE * 2 + 123, RATE + 7, RATE * 3 + 999, RATE // 2 + 1, RATE * 2 + 50, RATE + 333]
# Long enough for a build on four cores to encode in four segments and join them
LONG_BLOCK_SAMPLES = [RATE * 19 + 11, RATE * 23 + 503, RATE * 17 + 1, RATE * 21 + 77, RATE * 18 + 900, RATE * 22 + 3]


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
    return await _cached_book(client, session, kokoro, app, BLOCK_SAMPLES)


@pytest.fixture
async def long_book(client, session, kokoro, app) -> uuid.UUID:
    """Noisy tones: on clean ones two MP3 encoders soon write the same frames, which would hide a join gone wrong."""
    return await _cached_book(client, session, kokoro, app, LONG_BLOCK_SAMPLES, noise=True)


async def _cached_book(client, session, kokoro, app, block_samples: list[int], noise: bool = False) -> uuid.UUID:
    content = "\n\n".join(f"Paragraph {i} of the book is read aloud." for i in range(len(block_samples)))
    response = await client.post("/v1/documents/text", json={"content": content, "title": "A Book"})
    assert response.status_code == 201, response.text
    document_id = uuid.UUID(response.json()["id"])
    texts = (await session.get(Document, document_id)).audio_texts
    for idx, (text, samples) in enumerate(zip(texts, block_samples)):
        variant_hash = BlockVariant.get_hash(
            text=text, model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
        )
        audio = _ogg_opus(samples, pitch=idx + 1, noise=noise)
        if idx % 2:
            await app.state.redis_client.set(TTS_AUDIO_CACHE.format(hash=variant_hash), audio)
        else:
            await app.state.audio_cache.store(variant_hash, audio)
    return document_id


def _ogg_opus(samples: int, pitch: int, noise: bool = False) -> bytes:
    """A block as the Kokoro worker writes it: 24 kHz mono int16 PCM as 48 kbps Ogg Opus; noise is the same for a pitch each time."""
    pcm = np.sin(np.arange(samples) * 0.03 * pitch) * 8000
    if noise:
        rng = np.random.default_rng(pitch)
        envelope = np.repeat(rng.uniform(0, 6000, samples // 1200 + 1), 1200)[:samples]
        pcm += rng.normal(0, 1, samples) * envelope
    pcm = pcm.astype(np.int16)
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
    state = await built(client, app, document_id, ranges, fmt)
    assert state["status"] == "ready", state
    response = await client.get(f"/v1/documents/{document_id}/audio-export/{state['key']}.{fmt}")
    assert response.status_code == 200, response.text
    return response.content


async def built(client, app, document_id, ranges, fmt: str = "m4b") -> dict:
    """The export's state once its build has ended, as the tab watching the document hears it."""
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
    return state


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


def pitches(data: bytes, spans: list[tuple[float, float]]) -> list[int]:
    """The pitch (as _ogg_opus numbers it) heard in the middle of each span: the decoded audio's strongest frequency."""
    with av.open(io.BytesIO(data), "r") as container:
        rate = container.streams.audio[0].rate
        pcm = np.concatenate([frame.to_ndarray()[0] for frame in container.decode(audio=0)])
    heard = []
    for start, end in spans:
        middle = int((start + end) / 2 * rate)
        window = pcm[middle - rate // 10 : middle + rate // 10]
        hz = np.argmax(np.abs(np.fft.rfft(window * np.hanning(len(window))))) * rate / len(window)
        heard.append(round(hz / (0.03 * RATE / (2 * np.pi))))
    return heard


def spans(block_samples: list[int]) -> list[tuple[float, float]]:
    """Each block's (start, end) in seconds, the blocks laid end to end."""
    ends = np.cumsum(block_samples) / RATE
    return [(end - samples / RATE, end) for end, samples in zip(ends, block_samples)]


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_an_export_plays_a_sections_blocks_in_their_order(client, app, book, fmt):
    data = await exported(client, app, book, [(0, 5, "Whole book")], fmt)

    assert pitches(data, spans(BLOCK_SAMPLES)) == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_an_export_encoded_in_segments_plays_its_blocks_through_the_joins(
    client, app, long_book, fmt, monkeypatch
):
    in_one = await built_on(1, client, app, long_book, [(0, 5, "In one")], fmt, monkeypatch)

    data = await built_on(4, client, app, long_book, [(0, 2, "One"), (3, 5, "Two")], fmt, monkeypatch)

    duration, chapters = probe(data)
    blocks = spans(LONG_BLOCK_SAMPLES)
    assert duration == pytest.approx(blocks[-1][1], abs=0.001)
    assert [(t, start) for t, start, _ in chapters] == [("One", 0), ("Two", pytest.approx(blocks[3][0], abs=0.001))]
    assert pitches(data, blocks) == [1, 2, 3, 4, 5, 6]
    assert (window_errors(data) - window_errors(in_one)).max() < 6


async def test_an_mp3_join_holds_where_the_two_encoders_bit_reservoirs_differ(client, app, long_book, monkeypatch):
    in_one = await built_on(1, client, app, long_book, [(0, 5, "In one")], "mp3", monkeypatch)
    # Over the pre-roll the build gives them, LAME's encoders mostly end up writing the same frames
    monkeypatch.setattr(audio_export.audio_file, "PRE_ROLL", 8 * 576)

    data = await built_on(4, client, app, long_book, [(0, 5, "In four")], "mp3", monkeypatch)

    worse = window_errors(data) - window_errors(in_one)
    assert worse.any(), "the encoders wrote the same frames, so no join needed its reservoir rewritten"
    assert worse.max() < 6


async def built_on(cores: int, client, app, document_id, ranges, fmt: str, monkeypatch) -> bytes:
    monkeypatch.setattr(audio_export, "WORKERS", cores)
    return await exported(client, app, document_id, ranges, fmt)


def window_errors(data: bytes) -> np.ndarray:
    """The file's error, per 50 ms window, against the long book's blocks decoded one by one and laid end to end.

    In dB below that audio, after scaling it to the file's level: the stereo blocks reach MP3 3 dB
    quieter than AAC, since the downmix to the 32-bit integers LAME takes leaves headroom.
    """
    blocks = [(_ogg_opus(n, idx + 1, noise=True), n) for idx, n in enumerate(LONG_BLOCK_SAMPLES)]
    reference = np.concatenate([_decoded(block)[:samples] for block, samples in blocks])
    pcm = _decoded(data)
    window = RATE // 20
    n = min(len(pcm), len(reference)) // window * window
    pcm, reference = pcm[:n], reference[:n]
    reference = reference * np.dot(pcm, reference) / np.dot(reference, reference)
    noise = np.square(pcm - reference).reshape(-1, window).mean(axis=1)
    signal = np.square(reference[:n]).reshape(-1, window).mean(axis=1)
    return 10 * np.log10(noise / signal)


def _decoded(data: bytes) -> np.ndarray:
    """Audio as a player plays it: at RATE, the encoder's priming left out."""
    resampler = av.AudioResampler(format="dbl", layout="mono", rate=RATE)
    with av.open(io.BytesIO(data), "r") as container:
        frames = [f for frame in container.decode(audio=0) for f in resampler.resample(frame)] + resampler.resample(
            None
        )
    pcm = np.concatenate([f.to_ndarray()[0] for f in frames])
    return pcm[-frames[0].pts :] if frames[0].pts and frames[0].pts < 0 else pcm


async def test_an_export_builds_after_the_build_processes_died(client, app, book):
    await exported(client, app, book, [(0, 5, "Before")])
    for process in list(audio_export._pool()._processes.values()):
        process.kill()

    lost = await built(client, app, book, [(0, 5, "While dead")])
    data = await exported(client, app, book, [(0, 5, "After")])

    assert lost["status"] == "failed"
    assert probe(data)[0] == pytest.approx(seconds(0, 5), abs=0.001)


async def test_a_second_export_within_a_day_is_the_stored_file(client, app, book):
    first = await exported(client, app, book, [(0, 5, "Whole book")])

    response = await export(client, book, [(0, 5, "Whole book")])
    again = await client.get(f"/v1/documents/{book}/audio-export/{response.json()['key']}.m4b")

    assert response.json()["status"] == "ready"
    assert again.content == first


async def test_an_export_older_than_a_day_is_gone_and_a_fresh_one_stays(client, app, book):
    await exported(client, app, book, [(0, 5, "Whole book")], "m4b")
    await exported(client, app, book, [(0, 5, "Whole book")], "mp3")
    old_key = (await export(client, book, [(0, 5, "Whole book")], "m4b")).json()["key"]
    fresh_key = (await export(client, book, [(0, 5, "Whole book")], "mp3")).json()["key"]
    export_dir = Path(app.dependency_overrides[get_settings]().audio_export_dir)
    a_day_ago = time.time() - EXPORT_TTL_S - 1
    os.utime(export_dir / f"{old_key}.m4b", (a_day_ago, a_day_ago))

    old = await client.get(f"/v1/documents/{book}/audio-export/{old_key}.m4b")
    sweep_exports(export_dir)

    assert old.status_code == 404
    assert [p.name for p in export_dir.iterdir()] == [f"{fresh_key}.mp3"]
    assert (await client.get(f"/v1/documents/{book}/audio-export/{fresh_key}.mp3")).status_code == 200


async def test_an_export_with_a_block_not_prepared_is_refused(client, app, book, session, kokoro):
    texts = (await session.get(Document, book)).audio_texts
    gone = BlockVariant.get_hash(
        text=texts[2], model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
    )
    await app.state.audio_cache.delete(gone)

    response = await export(client, book, [(0, 5, "Whole book")])

    assert response.status_code == 409
    assert "1 of the 6 blocks" in response.json()["detail"]


async def test_an_export_leaves_out_a_block_with_no_audio(client, app, book, session, kokoro):
    texts = (await session.get(Document, book)).audio_texts
    silent = BlockVariant.get_hash(
        text=texts[2], model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
    )
    await app.state.audio_cache.delete(silent)
    await _process_result(app.state.redis_client, no_audio(book, 2, silent))

    duration, chapters = probe(await exported(client, app, book, [(0, 2, "One"), (3, 5, "Two")]))

    assert duration == pytest.approx(seconds(0, 1) + seconds(3, 5), abs=0.001)
    assert [start for _, start, _ in chapters] == pytest.approx([0, seconds(0, 1)], abs=0.001)


def no_audio(document_id: uuid.UUID, block_idx: int, variant_hash: str) -> WorkerResult:
    """The worker's result for a block it found nothing to say in."""
    return WorkerResult(
        job_id=uuid.uuid4(),
        variant_hash=variant_hash,
        user_id=DEFAULT_TEST_USER.id,
        document_id=document_id,
        block_idx=block_idx,
        model_slug="kokoro",
        voice_slug="af_heart",
        text_length=1,
        usage_multiplier=1.0,
        worker_id="stub",
        processing_time_ms=1,
        queue_wait_ms=1,
    )


async def test_an_export_whose_audio_leaves_the_cache_while_it_is_built_fails_rather_than_skip_it(
    client, app, book, session, kokoro, monkeypatch
):
    texts = (await session.get(Document, book)).audio_texts
    evicted = BlockVariant.get_hash(
        text=texts[2], model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
    )
    prepared_mask = audio_export.prepared_mask

    async def evict_once_checked(*args):
        mask = await prepared_mask(*args)
        await app.state.audio_cache.delete(evicted)
        return mask

    monkeypatch.setattr(audio_export, "prepared_mask", evict_once_checked)
    pubsub = app.state.redis_client.pubsub()
    await pubsub.subscribe(get_pubsub_channel(DEFAULT_TEST_USER.id, book))
    await pubsub.get_message(timeout=1)

    state = (await export(client, book, [(0, 5, "Whole book")])).json()
    while (message := await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)) is not None:
        if json.loads(message["data"])["type"] == "audio_export":
            state = json.loads(message["data"])
            break
    await pubsub.aclose()

    assert state["status"] == "failed"
    assert "left the cache" in state["error"]


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
    # 270,000 characters at the estimate's 14 a second: 5.4 hours, some 110 MiB of 48 kbps Opus
    content = "\n\n".join("A sentence of about fifty characters, read aloud here." * 5 for _ in range(1000))
    document_id = uuid.UUID((await client.post("/v1/documents/text", json={"content": content})).json()["id"])
    blocks = len((await session.get(Document, document_id)).audio_texts)

    whole = {
        "model": "kokoro",
        "voice": "af_heart",
        "ranges": [{"first_block": 0, "last_block": blocks - 1, "title": "All"}],
    }

    with audio_cache_of(app, max_size_mb=100):
        refused = await client.post(f"/v1/documents/{document_id}/audio-job", json=whole)
    queued = await app.state.redis_client.zcard(get_queue_name("kokoro")), await app.state.redis_client.hlen(TTS_JOBS)
    with audio_cache_of(app, max_size_mb=150):
        accepted = await client.post(f"/v1/documents/{document_id}/audio-job", json=whole)

    assert refused.status_code == 422
    assert "100 MB audio cache" in refused.json()["detail"]
    assert queued == (0, 0)
    assert accepted.status_code == 201
