"""Audio export: a selection's cached blocks joined into one audio file, with a chapter per section."""

import asyncio
import hashlib
import json
import multiprocessing
import os
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from yapit import audio_file
from yapit.audio_file import ChapterMark, Encoding
from yapit.contracts import TTS_AUDIO_CACHE, TTS_SKIPPED, get_pubsub_channel
from yapit.gateway.audio_job import prepared_mask
from yapit.gateway.cache import Cache
from yapit.gateway.metrics import log_error

EXPORT_TTL_S = 24 * 3600
SWEEP_INTERVAL_S = 3600
WORKERS = len(os.sched_getaffinity(0))  # segments a build is cut into
BUILD_NICENESS = 10
FETCH_BATCH = 64


class ExportFormat(StrEnum):
    m4b = "m4b"
    mp3 = "mp3"


ENCODINGS = {
    ExportFormat.m4b: Encoding(container="ipod", codec="aac"),
    ExportFormat.mp3: Encoding(container="mp3", codec="libmp3lame"),
}
MEDIA_TYPES = {ExportFormat.m4b: "audio/mp4", ExportFormat.mp3: "audio/mpeg"}


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
    """The user already has a build running; each keeps every core busy while it runs."""


@dataclass
class _Build:
    user_id: str
    task: asyncio.Task
    waiters: set[tuple[str, uuid.UUID]]


_builds: dict[str, _Build] = {}
_audio_pool: ProcessPoolExecutor | None = None


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
    scratch = export_dir / f".{key}.{uuid.uuid4().hex}"
    blocks_path, built = scratch.with_name(f"{scratch.name}.blocks"), scratch.with_name(f"{scratch.name}.built")
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
        blocks, marks = await _store_blocks(redis, cache, chapters, blocks_path)
        await audio_file.write_audio_file(_pool(), WORKERS, ENCODINGS[fmt], blocks_path, blocks, marks, built)
        os.replace(built, export_path(export_dir, key, fmt))
        logger.info(f"Audio export {key[:12]} ({fmt}) built in {time.monotonic() - started:.1f}s")
    except AudioNotCached as e:
        state = state.model_copy(update={"status": ExportStatus.failed, "error": str(e)})
    except Exception as e:
        if isinstance(e, BrokenProcessPool):
            _drop_pool()
        logger.exception(f"Audio export {key[:12]} failed: {e}")
        await log_error(f"Audio export failed: {e}")
        state = state.model_copy(update={"status": ExportStatus.failed, "error": "Building the audio file failed"})
    finally:
        blocks_path.unlink(missing_ok=True)
        built.unlink(missing_ok=True)
        build = _builds.pop(key)
    for user_id, document_id in build.waiters:
        message = WSAudioExport(document_id=document_id, **state.model_dump())
        await redis.publish(get_pubsub_channel(user_id, document_id), message.model_dump_json())


async def _store_blocks(
    redis: Redis, cache: Cache, chapters: list[Chapter], path: Path
) -> tuple[list[audio_file.Block], list[ChapterMark]]:
    """Fetch the chapters' blocks into one file, in order; returns where each block's audio lies and each chapter's span."""
    blocks, marks = [], []
    stream_at = 0
    with path.open("wb") as f:
        for chapter in chapters:
            start = stream_at
            for first in range(0, len(chapter.variant_hashes), FETCH_BATCH):
                for audio in await _fetch_audio(redis, cache, chapter.variant_hashes[first : first + FETCH_BATCH]):
                    samples = audio_file.block_samples(audio)
                    blocks.append(audio_file.Block(offset=f.tell(), size=len(audio), start=stream_at, samples=samples))
                    await asyncio.to_thread(f.write, audio)
                    stream_at += samples
            marks.append(ChapterMark(title=chapter.title, start=start, end=stream_at))
    return blocks, marks


def _pool() -> ProcessPoolExecutor:
    """The processes builds encode in, one per core, at low priority so that synthesis and requests come first.

    Started on first use, and again after a process of it died, which leaves a pool refusing all work.
    """
    global _audio_pool
    if _audio_pool is None:
        context = multiprocessing.get_context("forkserver")
        context.set_forkserver_preload(["yapit.audio_file"])
        _audio_pool = ProcessPoolExecutor(
            len(os.sched_getaffinity(0)), mp_context=context, initializer=os.nice, initargs=(BUILD_NICENESS,)
        )
    return _audio_pool


def _drop_pool() -> None:
    global _audio_pool
    if _audio_pool is not None:
        _audio_pool.shutdown(wait=False, cancel_futures=True)
        _audio_pool = None


async def _fetch_audio(redis: Redis, cache: Cache, hashes: list[str]) -> list[bytes]:
    """The blocks' audio in order, leaving out the blocks that have none."""
    hot = await redis.mget([TTS_AUDIO_CACHE.format(hash=h) for h in hashes])
    cold = await cache.batch_retrieve([h for h, audio in zip(hashes, hot) if audio is None])
    audio = [a if a is not None else cold.get(h) for h, a in zip(hashes, hot)]
    absent = [h for h, a in zip(hashes, audio) if a is None]
    if absent and await redis.exists(*[TTS_SKIPPED.format(hash=h) for h in absent]) < len(absent):
        raise AudioNotCached("Some of the audio left the cache while the file was built. Generate the audio again.")
    return [a for a in audio if a is not None]
