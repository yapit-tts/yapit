"""Audio export: a selection's cached blocks joined into one audio file, with a chapter per section."""

import asyncio
import hashlib
import io
import json
import os
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Literal

import av
import av.filter
from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit.contracts import TTS_AUDIO_CACHE, TTS_SKIPPED, get_pubsub_channel
from yapit.gateway.audio_job import prepared_mask
from yapit.gateway.cache import Cache
from yapit.gateway.metrics import log_error

EXPORT_TTL_S = 24 * 3600
SWEEP_INTERVAL_S = 3600
SAMPLE_RATE = 24_000
BIT_RATE = 64_000
FETCH_BATCH = 64
CORES = len(os.sched_getaffinity(0))
BUILD_NICENESS = 10


class ExportFormat(StrEnum):
    m4b = "m4b"
    mp3 = "mp3"


@dataclass(frozen=True)
class Encoding:
    container: str
    codec: str
    media_type: str
    options: dict[str, str]
    """The encoder's options, as FFmpeg names them."""


ENCODINGS = {
    ExportFormat.m4b: Encoding(container="ipod", codec="aac", media_type="audio/mp4", options={}),
    ExportFormat.mp3: Encoding(container="mp3", codec="libmp3lame", media_type="audio/mpeg", options={}),
}


@dataclass(frozen=True)
class Chapter:
    title: str
    variant_hashes: list[str]


class ExportStatus(StrEnum):
    building = "building"
    ready = "ready"
    failed = "failed"


class AudioExportState(BaseModel):
    key: str
    format: ExportFormat
    status: ExportStatus
    error: str | None = None


class WSAudioExport(AudioExportState):
    """An export's build ended; sent to the tabs of every user who asked for it while it was built."""

    type: Literal["audio_export"] = "audio_export"
    document_id: uuid.UUID


class AudioNotCached(Exception):
    pass


class ExportBusy(Exception):
    """The user already has a build running; each keeps an encoder and the threads decoding for it busy."""


@dataclass
class _Build:
    user_id: str
    task: asyncio.Task
    waiters: set[tuple[str, uuid.UUID]]


_builds: dict[str, _Build] = {}
# Below the gateway's own priority and the workers', so that requests and synthesis come first
_build_threads = ThreadPoolExecutor(
    CORES,
    thread_name_prefix="audio-export",
    initializer=lambda: os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), BUILD_NICENESS),
)


def export_key(fmt: ExportFormat, chapters: list[Chapter]) -> str:
    content = json.dumps([fmt, [[c.title, c.variant_hashes] for c in chapters]])
    return hashlib.sha256(content.encode()).hexdigest()


def export_path(export_dir: Path, key: str, fmt: ExportFormat) -> Path:
    return export_dir / f"{key}.{fmt}"


def stored_export(export_dir: Path, key: str, fmt: ExportFormat) -> Path | None:
    """The built file, unless it is older than EXPORT_TTL_S (the sweeper deletes it soon after)."""
    path = export_path(export_dir, key, fmt)
    try:
        if time.time() - path.stat().st_mtime < EXPORT_TTL_S:
            return path
    except FileNotFoundError:
        pass
    return None


async def request_export(
    redis: Redis,
    cache: Cache,
    export_dir: Path,
    user_id: str,
    document_id: uuid.UUID,
    fmt: ExportFormat,
    chapters: list[Chapter],
) -> AudioExportState:
    """The export's state, starting its build if no file is stored.

    Raises AudioNotCached if a block's audio is missing, and ExportBusy if the user's own build of another file runs.
    """
    key = export_key(fmt, chapters)
    if stored_export(export_dir, key, fmt):
        return AudioExportState(key=key, format=fmt, status=ExportStatus.ready)
    if build := _builds.get(key):
        build.waiters.add((user_id, document_id))
        return AudioExportState(key=key, format=fmt, status=ExportStatus.building)

    if any(b.user_id == user_id for b in _builds.values()):
        raise ExportBusy
    hashes = list(dict.fromkeys(h for c in chapters for h in c.variant_hashes))
    missing = len(hashes) - sum(await prepared_mask(redis, cache, hashes))
    if missing:
        raise AudioNotCached(f"{missing} of the {len(hashes)} blocks have no audio generated in this voice")

    task = asyncio.create_task(_build(redis, cache, export_dir, key, fmt, chapters))
    _builds[key] = _Build(user_id=user_id, task=task, waiters={(user_id, document_id)})
    return AudioExportState(key=key, format=fmt, status=ExportStatus.building)


async def run_export_sweeper(export_dir: Path) -> None:
    while True:
        sweep_exports(export_dir)
        await asyncio.sleep(SWEEP_INTERVAL_S)


def sweep_exports(export_dir: Path) -> None:
    """Delete exported files, and scratch files a crashed build left, once they are older than EXPORT_TTL_S."""
    cutoff = time.time() - EXPORT_TTL_S
    for path in export_dir.iterdir() if export_dir.exists() else []:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except FileNotFoundError:
            pass


async def _build(
    redis: Redis, cache: Cache, export_dir: Path, key: str, fmt: ExportFormat, chapters: list[Chapter]
) -> None:
    state = AudioExportState(key=key, format=fmt, status=ExportStatus.ready)
    started = time.monotonic()
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
        await write_audio_file(
            export_path(export_dir, key, fmt), fmt, chapters, lambda hashes: _fetch_audio(redis, cache, hashes)
        )
        logger.info(f"Audio export {key[:12]} ({fmt}) built in {time.monotonic() - started:.1f}s")
    except AudioNotCached as e:
        state = state.model_copy(update={"status": ExportStatus.failed, "error": str(e)})
    except Exception as e:
        logger.exception(f"Audio export {key[:12]} failed: {e}")
        await log_error(f"Audio export failed: {e}")
        state = state.model_copy(update={"status": ExportStatus.failed, "error": "Building the audio file failed"})
    finally:
        build = _builds.pop(key)
    for user_id, document_id in build.waiters:
        message = WSAudioExport(document_id=document_id, **state.model_dump())
        await redis.publish(get_pubsub_channel(user_id, document_id), message.model_dump_json())


async def _fetch_audio(redis: Redis, cache: Cache, hashes: list[str]) -> list[bytes]:
    """The blocks' audio in order, leaving out the blocks that have none."""
    hot = await redis.mget([TTS_AUDIO_CACHE.format(hash=h) for h in hashes])
    cold = await cache.batch_retrieve([h for h, audio in zip(hashes, hot) if audio is None])
    audio = [a if a is not None else cold.get(h) for h, a in zip(hashes, hot)]
    absent = [h for h, a in zip(hashes, audio) if a is None]
    if absent and await redis.exists(*[TTS_SKIPPED.format(hash=h) for h in absent]) < len(absent):
        raise AudioNotCached("Some of the audio left the cache while the file was built. Generate the audio again.")
    return [a for a in audio if a is not None]


async def write_audio_file(
    path: Path, fmt: ExportFormat, chapters: list[Chapter], fetch: Callable[[list[str]], Awaitable[list[bytes]]]
) -> None:
    """Decode the chapters' Ogg Opus blocks in order and encode them as one stream, then add the chapters.

    MP3 keeps its chapters in the ID3 tag at the head of the file, written before the first frame,
    and a chapter's start is known only once the blocks before it are decoded. So the stream is
    encoded first and copied, packet for packet, into the file that carries the chapters.
    """
    scratch = f".{path.name}.{uuid.uuid4().hex}"
    encoded, chaptered = path.parent / f"{scratch}.encoded", path.parent / f"{scratch}.chaptered"
    try:
        marks = await _encode(encoded, ENCODINGS[fmt], chapters, fetch)
        await _on_build_thread(_remux_with_chapters, encoded, chaptered, ENCODINGS[fmt], marks)
        os.replace(chaptered, path)
    finally:
        encoded.unlink(missing_ok=True)
        chaptered.unlink(missing_ok=True)


def _on_build_thread[T](fn: Callable[..., T], *args) -> asyncio.Future[T]:
    return asyncio.get_running_loop().run_in_executor(_build_threads, fn, *args)


async def _encode(
    path: Path, encoding: Encoding, chapters: list[Chapter], fetch: Callable[[list[str]], Awaitable[list[bytes]]]
) -> list[dict]:
    """Encode the chapters into path; returns each chapter's span in seconds of the stream."""
    out = av.open(str(path), "w", format=encoding.container)
    stream = out.add_stream(encoding.codec, rate=SAMPLE_RATE, layout="mono", options=encoding.options)
    assert isinstance(stream, av.AudioStream)
    stream.bit_rate = BIT_RATE
    stream.format = "fltp"  # LAME's default is integers, and FFmpeg's downmix to those halves the level
    time_base = Fraction(1, SAMPLE_RATE)

    def encode(block: av.AudioFrame, at: int) -> None:
        block.pts = at  # lets the muxer trim the encoder's priming
        block.time_base = time_base
        out.mux(stream.encode(block))

    def finish() -> None:
        out.mux(stream.encode(None))
        out.close()

    lengths = [0] * len(chapters)
    async for chapter, block in _decoded_blocks(chapters, fetch):
        await _on_build_thread(encode, block, sum(lengths))
        lengths[chapter] += block.samples
    await _on_build_thread(finish)
    marks, start = [], 0
    for chapter, length in zip(chapters, lengths):
        marks.append({"title": chapter.title, "start": start * time_base, "end": (start + length) * time_base})
        start += length
    return marks


async def _decoded_blocks(
    chapters: list[Chapter], fetch: Callable[[list[str]], Awaitable[list[bytes]]]
) -> AsyncIterator[tuple[int, av.AudioFrame]]:
    """Each block's audio in order, with its chapter's index; up to CORES blocks are decoded ahead of the one yielded."""
    ahead: deque[tuple[int, asyncio.Future[av.AudioFrame]]] = deque()
    for idx, chapter in enumerate(chapters):
        for first in range(0, len(chapter.variant_hashes), FETCH_BATCH):
            for audio in await fetch(chapter.variant_hashes[first : first + FETCH_BATCH]):
                ahead.append((idx, _on_build_thread(_decode_block, audio)))
                if len(ahead) > CORES:
                    of, block = ahead.popleft()
                    yield of, await block
    for of, block in ahead:
        yield of, await block


def _decode_block(audio: bytes) -> av.AudioFrame:
    """A block's audio as one mono frame at SAMPLE_RATE, cut to the length it was encoded from.

    FFmpeg's decoder leaves the encoder's end padding on a stream with a single audio page (a block
    under a second, such as a heading), which would put up to 13 ms of silence after it.

    One frame, because handing the encoder a frame costs more than encoding the 20 ms a decoded one holds.
    """
    with av.open(io.BytesIO(audio), "r") as block:
        stream = block.streams.audio[0]
        samples = _encoded_samples(audio, bytes(stream.codec_context.extradata or b""))
        graph = av.filter.Graph()
        graph.link_nodes(
            graph.add_abuffer(template=stream),
            graph.add("atrim", f"end_sample={samples}"),
            graph.add("aformat", f"sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=mono"),
            graph.add("abuffersink"),
        ).configure()
        for frame in [*block.decode(stream), None]:
            graph.push(frame)
    fifo = av.AudioFifo()
    try:
        while True:
            frame = graph.pull()
            assert isinstance(frame, av.AudioFrame)
            frame.pts = None
            fifo.write(frame)
    except av.EOFError:
        pass
    whole = fifo.read()
    assert whole is not None, "a cached block holds audio"
    return whole


def _encoded_samples(audio: bytes, opus_head: bytes) -> int:
    """Samples at 48 kHz in the PCM the block was encoded from.

    FFmpeg's Ogg muxer, which wrote every block the Kokoro worker and the gateway cache, sets the
    last page's granule position to the PCM's length plus twice the OpusHead's pre-skip.
    """
    last_page = _last_page(audio)
    granule = int.from_bytes(audio[last_page + 6 : last_page + 14], "little", signed=True)
    pre_skip = int.from_bytes(opus_head[10:12], "little")
    return granule - 2 * pre_skip


def _last_page(audio: bytes) -> int:
    """Offset of the last Ogg page: the "OggS" whose header and segments end the stream, not one inside a payload."""
    at = len(audio)
    while (at := audio.rfind(b"OggS", 0, at)) >= 0:
        if at + 27 > len(audio) or audio[at + 4] != 0:
            continue
        segments = audio[at + 27 : at + 27 + audio[at + 26]]
        if at + 27 + len(segments) + sum(segments) == len(audio):
            return at
    raise ValueError("No Ogg page ends the block")


def _remux_with_chapters(src_path: Path, dst_path: Path, encoding: Encoding, marks: list[dict]) -> None:
    with av.open(str(src_path), "r") as src:
        src_stream = src.streams.audio[0]
        dst = av.open(str(dst_path), "w", format=encoding.container)
        dst_stream = dst.add_stream_from_template(src_stream)
        dst.set_chapters(
            [
                {
                    "id": i + 1,
                    "start": round(m["start"] * 1000),
                    "end": round(m["end"] * 1000),
                    "time_base": Fraction(1, 1000),
                    "metadata": {"title": m["title"]},
                }
                for i, m in enumerate(marks)
            ]
        )
        for packet in src.demux(src_stream):
            if packet.dts is None:  # the demuxer's empty flush packet
                continue
            packet.stream = dst_stream
            dst.mux(packet)
        dst.close()
