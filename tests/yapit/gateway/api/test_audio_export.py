"""Audio export, driven at the HTTP API over real Ogg Opus blocks in the audio cache.

The expected durations are the PCM lengths each block was encoded from, so the file's length and
its chapters are checked against what went in, not against the join's own arithmetic.
"""

import asyncio
import io
import json
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest

from yapit.contracts import TTS_AUDIO_CACHE, TTS_JOBS, WorkerResult, get_pubsub_channel, get_queue_name
from yapit.gateway import audio_export
from yapit.gateway.audio_export import EXPORT_TTL_S, Chapter, ExportFormat, ExportStore, write_audio_file
from yapit.gateway.cache import CacheConfig
from yapit.gateway.config import get_settings
from yapit.gateway.domain_models import BlockVariant, Document, TTSModel, Voice
from yapit.gateway.result_consumer import _process_result
from yapit.workers.kokoro.ogg_opus import pcm_to_ogg_opus

from .conftest import DEFAULT_TEST_USER
from .test_audio_job import signed_in_as

RATE = 24_000
AMPLITUDE = 8000
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
async def book(client, session, kokoro, app, monkeypatch) -> uuid.UUID:
    """A document of six blocks, all in the cache: odd blocks in Redis only, as before the persister ran.

    The first three are stereo, as the Kokoro worker wrote blocks before it wrote mono.
    """
    # Two blocks decoded ahead of the encoder, so on any host a build of the six has to keep them in order
    monkeypatch.setattr(audio_export, "CORES", 2)
    content = "\n\n".join(f"Paragraph {i} of the book is read aloud." for i in range(len(BLOCK_SAMPLES)))
    response = await client.post("/v1/documents/text", json={"content": content, "title": "A Short Book"})
    assert response.status_code == 201, response.text
    document_id = uuid.UUID(response.json()["id"])
    texts = (await session.get(Document, document_id)).audio_texts
    for idx, (text, samples) in enumerate(zip(texts, BLOCK_SAMPLES)):
        variant_hash = BlockVariant.get_hash(
            text=text, model_slug="kokoro", voice_slug="af_heart", parameters=kokoro.parameters
        )
        # Pitch 1 (115 Hz) loses a fifth of its level through Opus, so the blocks start at pitch 2
        audio = _ogg_opus(samples, pitch=idx + 2, layout="stereo" if idx < 3 else "mono")
        if idx % 2:
            await app.state.redis_client.set(TTS_AUDIO_CACHE.format(hash=variant_hash), audio)
        else:
            await app.state.audio_cache.store(variant_hash, audio)
    return document_id


def _ogg_opus(samples: int, pitch: int, layout: str) -> bytes:
    """A block as the Kokoro worker writes it, or as it wrote it before: mono PCM upmixed into 48 kbps stereo Opus."""
    pcm = (np.sin(np.arange(samples) * 0.03 * pitch) * AMPLITUDE).astype(np.int16)
    if layout == "mono":
        return pcm_to_ogg_opus(pcm.tobytes())
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=RATE, layout="stereo")
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
    state = (await export_heard(client, app, document_id, ranges, fmt))[-1]
    assert state["status"] == "ready", state
    response = await client.get(f"/v1/documents/{document_id}/audio-export/{state['key']}.{fmt}")
    assert response.status_code == 200, response.text
    return response.content


async def export_heard(
    client, app, document_id, ranges, fmt: str = "m4b", disk: list[tuple[int, int]] | None = None
) -> list[dict]:
    """The export's answer, then what the tab watching the document hears of it, up to the end of its build.

    disk gets the bytes in the export directory, and those the store counts, each time the tab hears of the build.
    """
    pubsub = app.state.redis_client.pubsub()
    await pubsub.subscribe(get_pubsub_channel(DEFAULT_TEST_USER.id, document_id))
    await pubsub.get_message(timeout=1)
    states = [(await export(client, document_id, ranges, fmt)).json()]
    while states[-1]["status"] == "building":
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
        assert message is not None, "the build never ended"
        if disk is not None:
            disk.append(sampled(app))
        heard = json.loads(message["data"])
        if heard["type"] == "audio_export" and heard["key"] == states[0]["key"]:
            states.append(heard)
    await pubsub.aclose()
    return states


def export_dir(app) -> Path:
    return Path(app.dependency_overrides[get_settings]().audio_export_dir)


def bytes_on_disk(app) -> int:
    return sum(p.stat().st_size for p in export_dir(app).iterdir())


def sampled(app) -> tuple[int, int]:
    return bytes_on_disk(app), app.state.export_store.taken


def within(disk: list[tuple[int, int]], max_bytes: int) -> bool:
    """Whether the directory held no more than max_bytes, and no more than the store counted, at every sample."""
    return all(on_disk <= counted <= max_bytes for on_disk, counted in disk)


def keep_at_most(app, max_bytes: int) -> ExportStore:
    """The gateway's saved audio files from now on kept within max_bytes."""
    app.state.export_store = ExportStore.open(export_dir(app), max_bytes)
    return app.state.export_store


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
    """The pitch (as _ogg_opus numbers it) heard in the middle of each span, from the decoded audio's zero crossings."""
    with av.open(io.BytesIO(data), "r") as container:
        rate = container.streams.audio[0].rate
        pcm = np.concatenate([frame.to_ndarray()[0] for frame in container.decode(audio=0)])
    heard = []
    for start, end in spans:
        middle = int((start + end) / 2 * rate)
        window = pcm[middle - rate // 10 : middle + rate // 10]
        crossings = np.count_nonzero(np.diff(np.signbit(window)))
        hz = crossings / 2 / 0.2
        heard.append(round(hz / (0.03 * RATE / (2 * np.pi))))
    return heard


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_an_export_plays_a_sections_blocks_in_their_order(client, app, book, fmt):
    data = await exported(client, app, book, [(0, 5, "Whole book")], fmt)

    starts = [seconds(0, idx - 1) if idx else 0.0 for idx in range(len(BLOCK_SAMPLES))]
    spans = [(start, start + samples / RATE) for start, samples in zip(starts, BLOCK_SAMPLES)]
    assert pitches(data, spans) == [2, 3, 4, 5, 6, 7]


@pytest.mark.parametrize("fmt", ["m4b", "mp3"])
async def test_an_export_plays_each_block_at_the_level_it_plays_at_on_its_own(client, app, book, fmt):
    data = await exported(client, app, book, [(0, 5, "Whole book")], fmt)

    with av.open(io.BytesIO(data), "r") as container:
        rate = container.streams.audio[0].rate
        pcm = np.concatenate([frame.to_ndarray()[0] for frame in container.decode(audio=0)])
    starts = [seconds(0, idx - 1) if idx else 0.0 for idx in range(len(BLOCK_SAMPLES))]
    middles = [int((start + samples / RATE / 2) * rate) for start, samples in zip(starts, BLOCK_SAMPLES)]
    levels = [np.sqrt(2 * np.mean(np.square(pcm[m - rate // 10 : m + rate // 10]))) * 32768 for m in middles]
    # A stereo block's channels each carry 1/sqrt(2) of its PCM, and mono blocks are written to match
    assert levels == pytest.approx([AMPLITUDE / np.sqrt(2)] * 6, rel=0.1)


async def test_a_build_tells_the_tab_how_many_of_its_blocks_are_encoded(client, app, book):
    states = await export_heard(client, app, book, [(0, 2, "One"), (3, 5, "Two")])

    assert [s["status"] for s in states] == ["building"] * 7 + ["ready"]
    assert [s["progress"] for s in states[:-1]] == pytest.approx([0, 1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6, 1])


async def test_a_build_runs_below_the_gateways_priority(client, app, book):
    await exported(client, app, book, [(0, 5, "Whole book")])

    builders = [thread.native_id for thread in threading.enumerate() if thread.name.startswith("audio-export")]

    gateway = os.getpriority(os.PRIO_PROCESS, 0)
    assert builders and all(os.getpriority(os.PRIO_PROCESS, tid) > gateway for tid in builders)


async def test_a_second_export_within_a_day_is_the_stored_file(client, app, book):
    first = await exported(client, app, book, [(0, 5, "Whole book")])

    response = await export(client, book, [(0, 5, "Whole book")])
    again = await client.get(f"/v1/documents/{book}/audio-export/{response.json()['key']}.m4b")

    assert response.json()["status"] == "ready"
    assert again.content == first


async def test_an_export_older_than_a_day_is_gone_and_a_fresh_one_stays(client, app, book, monkeypatch):
    a_day_ago = time.time() - EXPORT_TTL_S - 1
    monkeypatch.setattr(audio_export, "time", SimpleNamespace(time=lambda: a_day_ago, monotonic=time.monotonic))
    old_key = (await export_heard(client, app, book, [(0, 5, "Whole book")], "m4b"))[-1]["key"]
    monkeypatch.setattr(audio_export, "time", time)
    fresh_key = (await export_heard(client, app, book, [(0, 5, "Whole book")], "mp3"))[-1]["key"]

    old = await client.get(f"/v1/documents/{book}/audio-export/{old_key}.m4b")
    app.state.export_store.sweep()

    assert old.status_code == 404
    assert [p.name for p in export_dir(app).iterdir()] == [f"{fresh_key}.mp3"]
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

    state = (await export_heard(client, app, book, [(0, 5, "Whole book")]))[-1]

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
    # 270,000 characters at the estimate's 14 a second: 5.4 hours, some 74 MiB of 32 kbps Opus
    content = "\n\n".join("A sentence of about fifty characters, read aloud here." * 5 for _ in range(1000))
    document_id = uuid.UUID((await client.post("/v1/documents/text", json={"content": content})).json()["id"])
    blocks = len((await session.get(Document, document_id)).audio_texts)

    whole = {
        "model": "kokoro",
        "voice": "af_heart",
        "ranges": [{"first_block": 0, "last_block": blocks - 1, "title": "All"}],
    }

    with audio_cache_of(app, max_size_mb=70):
        refused = await client.post(f"/v1/documents/{document_id}/audio-job", json=whole)
    queued = await app.state.redis_client.zcard(get_queue_name("kokoro")), await app.state.redis_client.hlen(TTS_JOBS)
    with audio_cache_of(app, max_size_mb=80):
        accepted = await client.post(f"/v1/documents/{document_id}/audio-job", json=whole)

    assert refused.status_code == 422
    assert "70 MB audio cache" in refused.json()["detail"]
    assert queued == (0, 0)
    assert accepted.status_code == 201


# The whole book is some 78 KB as a file. Its build holds up to some 156 KB of room: twice the bit
# rate while it encodes, then both copies of the stream while the chapters are added.


@pytest.mark.parametrize("fmt", list(ExportFormat))
@pytest.mark.parametrize(
    "selection",
    [[(0, 5, "Whole book")], [(3, 3, "Ü" * 500)] * 100, [(3, 3, "")] * 100],  # chapters outweigh their audio
    ids=["book", "long-titles", "short-titles"],
)
async def test_a_build_writes_no_more_than_the_room_it_holds(tmp_path, fmt, selection, monkeypatch):
    blocks = [_ogg_opus(samples, pitch=idx + 1) for idx, samples in enumerate(BLOCK_SAMPLES)]
    chapters = [Chapter(title=t, variant_hashes=[str(i) for i in range(f, last + 1)]) for f, last, t in selection]
    granted, overdrawn = [0], []

    async def fetch(hashes: list[str]) -> list[bytes]:
        return [blocks[int(h)] for h in hashes]

    async def no_progress(_: float) -> None:
        pass

    def check() -> None:
        on_disk = sum(p.stat().st_size for p in tmp_path.iterdir())
        if on_disk > granted[0]:
            overdrawn.append((on_disk, granted[0]))

    def reserve(total: int) -> None:
        check()
        granted[0] = total

    remux = audio_export._remux_with_chapters

    def remux_then_check(*args) -> None:  # both copies of the stream are on disk here
        remux(*args)
        check()

    monkeypatch.setattr(audio_export, "_remux_with_chapters", remux_then_check)
    await write_audio_file(tmp_path / f"file.{fmt}", fmt, chapters, fetch, no_progress, reserve)

    assert overdrawn == []
    assert (tmp_path / f"file.{fmt}").stat().st_size <= granted[0]


async def test_however_many_files_are_asked_for_they_take_no_more_than_the_bound_and_the_oldest_go_first(
    client, app, book
):
    store = keep_at_most(app, 400_000)
    disk: list[tuple[int, int]] = []

    takes = [await export_heard(client, app, book, [(0, 5, f"Take {i}")], disk=disk) for i in range(8)]

    keys = [states[-1]["key"] for states in takes]
    kept = sorted(p.stem for p in export_dir(app).iterdir())
    first = await client.get(f"/v1/documents/{book}/audio-export/{keys[0]}.m4b")
    assert [states[-1]["status"] for states in takes] == ["ready"] * 8
    assert within(disk, 400_000)
    assert 0 < len(kept) < 8 and kept == sorted(keys[-len(kept) :])
    assert first.status_code == 404 and "Save it again" in first.json()["detail"]
    assert store.taken == bytes_on_disk(app)


async def test_a_file_larger_than_the_bound_fails_saying_so_and_leaves_nothing_behind(client, app, book):
    store = keep_at_most(app, 150_000)
    disk: list[tuple[int, int]] = []

    state = (await export_heard(client, app, book, [(0, 5, "Whole book")], disk=disk))[-1]

    assert state["status"] == "failed"
    assert "too large for the 0 MB" in state["error"] and "Pick fewer sections" in state["error"]
    assert within(disk, 150_000)
    assert list(export_dir(app).iterdir()) == []
    assert store.taken == 0


async def test_a_file_being_downloaded_is_not_deleted_and_downloads_whole(client, app, book):
    keep_at_most(app, 200_000)  # room for the held file or a build, not both
    held = (await export_heard(client, app, book, [(0, 5, "Held")]))[-1]["key"]

    async with paused_download(app, f"/v1/documents/{book}/audio-export/{held}.m4b") as download:
        crowded = (await export_heard(client, app, book, [(0, 5, "Crowding it out")]))[-1]
    status, headers, body = await download
    after = (await export_heard(client, app, book, [(0, 5, "Crowding it out")]))[-1]
    gone = await client.get(f"/v1/documents/{book}/audio-export/{held}.m4b")

    assert crowded["status"] == "failed" and "Save again" in crowded["error"]
    assert status == 200 and int(headers[b"content-length"]) == len(body)
    assert probe(body)[0] == pytest.approx(seconds(0, 5), abs=0.001)
    assert after["status"] == "ready"
    assert gone.status_code == 404


@asynccontextmanager
async def paused_download(app, path: str):
    """A GET of path through the ASGI app that stops after its first chunk until the block exits.

    Yields the download's task, which gives (status, headers, body) once it has run to the end.
    """
    first_chunk, go_on = asyncio.Event(), asyncio.Event()
    started: dict = {}
    body = bytearray()

    async def receive():
        if not started:
            started["receive"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.start":
            started.update(status=message["status"], headers=dict(message["headers"]))
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))
            if message.get("more_body") and not first_chunk.is_set():
                first_chunk.set()
                await go_on.wait()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }

    async def run():
        await app(scope, receive, send)
        return started["status"], started["headers"], bytes(body)

    task = asyncio.create_task(run())
    await asyncio.wait_for(first_chunk.wait(), timeout=10)
    try:
        yield task
    finally:
        go_on.set()


async def test_two_builds_at_once_at_the_bound_stay_within_it(client, app, book, session, monkeypatch):
    store = keep_at_most(app, 250_000)  # room for one build and the other's file, not for both builds
    doc = await session.get(Document, book)
    doc.is_public = True
    await session.commit()
    both_started = asyncio.Event()
    fetch_audio = audio_export._fetch_audio

    async def once_both_started(*args):
        await both_started.wait()
        return await fetch_audio(*args)

    monkeypatch.setattr(audio_export, "_fetch_audio", once_both_started)
    pubsub = app.state.redis_client.pubsub()
    for user in ["reader-a", "reader-b"]:
        await pubsub.subscribe(get_pubsub_channel(user, book))
        await pubsub.get_message(timeout=1)
    keys = []
    for user in ["reader-a", "reader-b"]:
        with signed_in_as(app, user):
            keys.append((await export(client, book, [(0, 5, user)])).json()["key"])
    both_started.set()

    ends, disk = {}, []
    while len(ends) < 2:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
        assert message is not None, "a build never ended"
        disk.append(sampled(app))
        heard = json.loads(message["data"])
        if heard["status"] != "building":
            ends[heard["key"]] = heard
    await pubsub.aclose()

    assert within(disk, 250_000)
    assert all(e["status"] == "ready" or "Save again" in e["error"] for e in ends.values())
    assert store.taken == bytes_on_disk(app)
