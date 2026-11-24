"""Audio export: a selection's cached blocks joined into one audio file, with a chapter per section."""

import asyncio
import hashlib
import io
import json
import os
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
# Twice the bit rate: both encoders were measured writing at most 15% more than it, container included
ROOM_PER_SAMPLE = 2 * BIT_RATE / 8 / SAMPLE_RATE
# Per chapter, beside twice its title's bytes: the containers were measured adding under 1 KB for
# the first chapter and some 100 bytes for each after
ROOM_PER_CHAPTER = 2048
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
    ExportFormat.m4b: Encoding(container="ipod", codec="aac", media_type="audio/mp4", options={"aac_coder": "fast"}),
    ExportFormat.mp3: Encoding(
        container="mp3", codec="libmp3lame", media_type="audio/mpeg", options={"compression_level": "7"}
    ),
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
    progress: float | None = None
    """While building: the fraction of the selection's blocks that are encoded."""
    error: str | None = None


class WSAudioExport(AudioExportState):
    """An export's build got a percent further, or ended; sent to the tabs of every user who asked for it while it was built."""

    type: Literal["audio_export"] = "audio_export"
    document_id: uuid.UUID


class AudioNotCached(Exception):
    pass


class ExportBusy(Exception):
    """The user already has a build running; each keeps an encoder and the threads decoding for it busy."""


class NoRoom(Exception):
    """The saved audio files leave no room for a build's file; the message says what the user can do."""


@dataclass
class _File:
    size: int
    built: float


@dataclass
class ExportStore:
    """The files in the export directory, kept within max_bytes with the room the running builds hold.

    A build holds room for its files before it writes them, and the oldest files no download holds are
    deleted to make it. Every method runs on the event loop with no await, so none interleaves another.
    """

    dir: Path
    max_bytes: int
    _files: dict[str, _File] = field(default_factory=dict, init=False)
    """By name, oldest first."""
    _stored_bytes: int = field(default=0, init=False)
    _rooms: dict[str, int] = field(default_factory=dict, init=False)
    """By build key: the bytes its files may take."""
    _foreign_bytes: int = field(default=0, init=False)
    """Scratch of builds this gateway does not run, as last swept."""
    _held: Counter[str] = field(default_factory=Counter, init=False)
    """By name: the downloads serving it."""

    @classmethod
    def open(cls, dir: Path, max_bytes: int) -> "ExportStore":
        dir.mkdir(parents=True, exist_ok=True)
        store = cls(dir, max_bytes)
        store.sweep()
        return store

    @property
    def taken(self) -> int:
        """The bytes counted against max_bytes: the files, the running builds' room, and others' scratch."""
        return self._stored_bytes + sum(self._rooms.values()) + self._foreign_bytes

    def path(self, key: str, fmt: ExportFormat) -> Path:
        return self.dir / f"{key}.{fmt}"

    def stored(self, key: str, fmt: ExportFormat) -> Path | None:
        """The built file, unless it is older than EXPORT_TTL_S (the sweep deletes it soon after).

        A file found here that this store did not write is counted, which can delete the oldest files.
        """
        path = self.path(key, fmt)
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._forget(path.name)
            return None
        if path.name not in self._files:
            self._add(path.name, _File(stat.st_size, stat.st_mtime))
            self._files = _oldest_first(self._files)
            self._make_room(0)
        file = self._files.get(path.name)
        return path if file and time.time() - file.built < EXPORT_TTL_S else None

    def reserve(self, key: str, total: int) -> None:
        """Let the build's files take total bytes, deleting the oldest files to make room.

        Raises NoRoom, deleting nothing, where deleting every file no download holds would not make it.
        """
        if total > self.max_bytes:
            raise NoRoom(
                f"This file is too large for the {self.max_bytes // 2**20:,} MB the server keeps "
                "for audio files. Pick fewer sections."
            )
        if not self._make_room(total - self._rooms.get(key, 0)):
            raise NoRoom("The server has no room for another audio file right now. Save again in a few minutes.")
        self._rooms[key] = total

    def shelve(self, key: str, path: Path) -> None:
        """Count the file a build wrote in place of the room the build held."""
        self._forget(path.name)
        self._add(path.name, _File(path.stat().st_size, time.time()))
        self._rooms.pop(key, None)
        self._make_room(0)

    def release(self, key: str) -> None:
        self._rooms.pop(key, None)

    def hold(self, path: Path) -> Callable[[], None]:
        """Keep the file from deletion while a download serves it; the callable returned lets it go."""
        self._held[path.name] += 1

        def release() -> None:
            self._held[path.name] -= 1
            if not self._held[path.name]:
                del self._held[path.name]

        return release

    def sweep(self) -> None:
        """Count what the directory holds, and delete expired files and scratch nothing wrote for an hour."""
        now = time.time()
        found: dict[str, _File] = {}
        foreign = 0
        for entry in os.scandir(self.dir):
            try:
                stat = entry.stat()
                if not entry.name.startswith("."):
                    found[entry.name] = self._files.get(entry.name) or _File(stat.st_size, stat.st_mtime)
                elif any(entry.name.startswith(f".{key}.") for key in self._rooms):
                    pass
                elif now - stat.st_mtime > SWEEP_INTERVAL_S:
                    os.unlink(entry.path)
                else:
                    foreign += stat.st_size
            except FileNotFoundError:
                pass
        self._files = _oldest_first(found)
        self._stored_bytes = sum(f.size for f in self._files.values())
        self._foreign_bytes = foreign
        for name, file in list(self._files.items()):
            if now - file.built >= EXPORT_TTL_S and not self._held[name]:
                self._delete(name)
        self._make_room(0)

    def _make_room(self, size: int) -> bool:
        """Delete the oldest files no download holds until size more bytes fit; False, deleting none, if they cannot."""
        excess = self.taken + size - self.max_bytes
        if excess <= 0:
            return True
        held = sum(self._files[name].size for name in self._held if name in self._files)
        if self._stored_bytes - held < excess:
            return False
        while excess > 0:
            name = next(name for name in self._files if not self._held[name])
            excess -= self._files[name].size
            self._delete(name)
        return True

    def _add(self, name: str, file: _File) -> None:
        self._files[name] = file
        self._stored_bytes += file.size

    def _forget(self, name: str) -> None:
        if file := self._files.pop(name, None):
            self._stored_bytes -= file.size

    def _delete(self, name: str) -> None:
        (self.dir / name).unlink(missing_ok=True)
        self._forget(name)


def _oldest_first(files: dict[str, _File]) -> dict[str, _File]:
    return dict(sorted(files.items(), key=lambda item: item[1].built))


@dataclass
class _Build:
    user_id: str
    task: asyncio.Task
    waiters: set[tuple[str, uuid.UUID]]
    progress: float = 0


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


async def request_export(
    redis: Redis,
    cache: Cache,
    store: ExportStore,
    user_id: str,
    document_id: uuid.UUID,
    fmt: ExportFormat,
    chapters: list[Chapter],
) -> AudioExportState:
    """The export's state, starting its build if no file is stored.

    Raises AudioNotCached if a block's audio is missing, and ExportBusy if the user's own build of another file runs.
    """
    key = export_key(fmt, chapters)
    if store.stored(key, fmt):
        return AudioExportState(key=key, format=fmt, status=ExportStatus.ready)
    if build := _builds.get(key):
        build.waiters.add((user_id, document_id))
        return AudioExportState(key=key, format=fmt, status=ExportStatus.building, progress=build.progress)

    if any(b.user_id == user_id for b in _builds.values()):
        raise ExportBusy
    hashes = list(dict.fromkeys(h for c in chapters for h in c.variant_hashes))
    missing = len(hashes) - sum(await prepared_mask(redis, cache, hashes))
    if missing:
        raise AudioNotCached(f"{missing} of the {len(hashes)} blocks have no audio generated in this voice")

    task = asyncio.create_task(_build(redis, cache, store, key, fmt, chapters))
    _builds[key] = _Build(user_id=user_id, task=task, waiters={(user_id, document_id)})
    return AudioExportState(key=key, format=fmt, status=ExportStatus.building, progress=0)


async def run_export_sweeper(store: ExportStore) -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_S)
        store.sweep()


async def _build(
    redis: Redis, cache: Cache, store: ExportStore, key: str, fmt: ExportFormat, chapters: list[Chapter]
) -> None:
    state = AudioExportState(key=key, format=fmt, status=ExportStatus.ready)
    started = time.monotonic()
    build = _builds[key]

    async def tell_waiters(state: AudioExportState) -> None:
        for user_id, document_id in list(build.waiters):
            message = WSAudioExport(document_id=document_id, **state.model_dump())
            await redis.publish(get_pubsub_channel(user_id, document_id), message.model_dump_json())

    async def on_progress(progress: float) -> None:
        a_percent_further = int(progress * 100) > int(build.progress * 100)
        build.progress = progress
        if a_percent_further:
            await tell_waiters(state.model_copy(update={"status": ExportStatus.building, "progress": progress}))

    path = store.path(key, fmt)
    try:
        await write_audio_file(
            path,
            fmt,
            chapters,
            lambda hashes: _fetch_audio(redis, cache, hashes),
            on_progress,
            lambda total: store.reserve(key, total),
        )
        store.shelve(key, path)
        logger.info(f"Audio export {key[:12]} ({fmt}) built in {time.monotonic() - started:.1f}s")
    except (AudioNotCached, NoRoom) as e:
        state = state.model_copy(update={"status": ExportStatus.failed, "error": str(e)})
    except Exception as e:
        logger.exception(f"Audio export {key[:12]} failed: {e}")
        await log_error(f"Audio export failed: {e}")
        state = state.model_copy(update={"status": ExportStatus.failed, "error": "Building the audio file failed"})
    finally:
        store.release(key)
        del _builds[key]
    await tell_waiters(state)


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
    path: Path,
    fmt: ExportFormat,
    chapters: list[Chapter],
    fetch: Callable[[list[str]], Awaitable[list[bytes]]],
    on_progress: Callable[[float], Awaitable[None]],
    reserve: Callable[[int], None],
) -> None:
    """Decode the chapters' Ogg Opus blocks in order and encode them as one stream, then add the chapters.

    on_progress hears the fraction of the blocks that are encoded, after each. reserve hears the bytes
    the build's files may take in all before they take more, and raises to stop the build.

    MP3 keeps its chapters in the ID3 tag at the head of the file, written before the first frame,
    and a chapter's start is known only once the blocks before it are decoded. So the stream is
    encoded first and copied, packet for packet, into the file that carries the chapters.
    """
    scratch = f".{path.name}.{uuid.uuid4().hex}"
    encoded, chaptered = path.parent / f"{scratch}.encoded", path.parent / f"{scratch}.chaptered"
    try:
        marks = await _encode(encoded, ENCODINGS[fmt], chapters, fetch, on_progress, reserve)
        titles = sum(2 * len(c.title.encode()) + ROOM_PER_CHAPTER for c in chapters)
        reserve(2 * encoded.stat().st_size + titles)
        await _on_build_thread(_remux_with_chapters, encoded, chaptered, ENCODINGS[fmt], marks)
        os.replace(chaptered, path)
    finally:
        encoded.unlink(missing_ok=True)
        chaptered.unlink(missing_ok=True)


def _on_build_thread[T](fn: Callable[..., T], *args) -> asyncio.Future[T]:
    return asyncio.get_running_loop().run_in_executor(_build_threads, fn, *args)


async def _encode(
    path: Path,
    encoding: Encoding,
    chapters: list[Chapter],
    fetch: Callable[[list[str]], Awaitable[list[bytes]]],
    on_progress: Callable[[float], Awaitable[None]],
    reserve: Callable[[int], None],
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
    blocks = sum(len(c.variant_hashes) for c in chapters)
    encoded = 0
    async for chapter, block in _decoded_blocks(chapters, fetch):
        reserve(round((sum(lengths) + block.samples) * ROOM_PER_SAMPLE))
        await _on_build_thread(encode, block, sum(lengths))
        lengths[chapter] += block.samples
        encoded += 1
        await on_progress(encoded / blocks)
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

    A stereo block holds the same speech in both channels, and plays at the level of one; mixing the
    two down would put it 3 dB above a mono block.
    """
    with av.open(io.BytesIO(audio), "r") as block:
        stream = block.streams.audio[0]
        samples = _encoded_samples(audio, bytes(stream.codec_context.extradata or b""))
        graph = av.filter.Graph()
        graph.link_nodes(
            graph.add_abuffer(template=stream),
            graph.add("atrim", f"end_sample={samples}"),
            graph.add("pan", "mono|c0=c0"),
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
