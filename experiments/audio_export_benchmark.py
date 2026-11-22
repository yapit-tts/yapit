"""Time an audio export's build over blocks cut from a speech recording, and check the file it builds.

The blocks are what the Kokoro worker caches: 24 kHz mono speech as 48 kbps Ogg Opus, cut from any
recording PyAV reads at lengths drawn from a fixed seed, and kept in --scratch so every run builds
from the same bytes. A build runs as the gateway runs it, from the blocks stored in one file, in
the gateway's pool of build processes; --before times the join a copy of an older
`yapit/gateway/audio_export.py` makes instead. Every built file is checked: duration equal to the
blocks' sum, one chapter per section, and the decoded audio compared with the blocks' own.

Examples:
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --runs 5
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --before old_audio_export.py --runs 5
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --selection ten-hours --format mp3
"""

import asyncio
import importlib.util
import io
import json
import os
import pickle
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import av
import numpy as np
import tyro

from yapit import audio_file
from yapit.audio_file import Block, ChapterMark
from yapit.contracts import KOKORO_OPUS_BITRATE

# The gateway is imported where it is used: a build process imports this script as its main module,
# and importing the gateway there would take seconds each.
RATE = audio_file.SAMPLE_RATE
SELECTIONS = {
    # The build max timed on production: 5 min 10 s in 23 blocks, one section.
    "five-minutes": {"seconds": 310, "blocks": 23, "sections": 1},
    # A long audiobook: blocks of about the five-minute selection's mean length, 30 sections.
    "ten-hours": {"seconds": 36_000, "blocks": 2_700, "sections": 30},
}


@dataclass(frozen=True)
class Section:
    title: str
    variant_hashes: list[str]


@dataclass
class Args:
    speech: Path
    """A speech recording, in any format PyAV reads; the blocks are cut from it, cycling through it as often as needed."""
    selection: Literal["five-minutes", "ten-hours"] = "five-minutes"
    """The selection to build."""
    format: Literal["m4b", "mp3"] = "m4b"
    """The file to build."""
    runs: int = 1
    """Builds to time, one after another."""
    before: Path | None = None
    """A copy of an older audio_export.py whose write_audio_file to time instead of the current build."""
    stages: bool = False
    """Time each stage of one build instead of the whole build; the current build's after one build that starts its processes."""
    compare: bool = True
    """Decode each built file and compare it with the blocks' own audio, around every join and over the whole file."""
    scratch: Path = Path(tempfile.gettempdir()) / "audio-export-benchmark"
    """Where the blocks and the built files are kept."""
    out: Path | None = None
    """A file each run's result is appended to, as one JSON line."""


def main(args: Args) -> None:
    args.scratch.mkdir(parents=True, exist_ok=True)
    blocks, chapters = corpus(args.speech, args.selection, args.scratch)
    audio_s = sum(audio_file.block_samples(b) for b in blocks.values()) / RATE
    fmt = args.format
    side = "before" if args.before else "after"
    print(f"{args.selection}: {len(blocks)} blocks, {len(chapters)} sections, {audio_s:.1f} s of audio")

    if args.stages:
        stages = (
            time_stages(_load(args.before), fmt, chapters, blocks)
            if args.before
            else time_stages_after(fmt, chapters, blocks, args.scratch)
        )
        report(args, {"side": side, "stages": stages})
        return
    build = _before(_load(args.before), blocks) if args.before else _after(blocks)
    path = args.scratch / f"build.{fmt}"
    for _ in range(args.runs):
        started = time.perf_counter()
        joins = build(path, fmt, chapters)
        wall = time.perf_counter() - started
        duration, titles = probe(path)
        result = {"side": side, "wall_s": round(wall, 3), "audio_s": round(audio_s, 3), "file_s": round(duration, 4)}
        result["ok"] = abs(duration - audio_s) < 0.001 and titles == [c.title for c in chapters]
        if args.compare:
            result |= compare(path, blocks, chapters, joins)
        report(args, result)


def _store(
    blocks: dict[str, bytes], chapters: list[Section], blocks_path: Path
) -> tuple[list[Block], list[ChapterMark]]:
    """The blocks in one file, as the gateway stores them as it fetches them."""
    stored, marks, at = [], [], 0
    with blocks_path.open("wb") as f:
        for chapter in chapters:
            start = at
            for h in chapter.variant_hashes:
                samples = audio_file.block_samples(blocks[h])
                stored.append(Block(offset=f.tell(), size=len(blocks[h]), start=at, samples=samples))
                f.write(blocks[h])
                at += samples
            marks.append(ChapterMark(title=chapter.title, start=start, end=at))
    return stored, marks


def _after(blocks: dict[str, bytes]):
    """The build as the gateway runs it, from the point its blocks are fetched; returns where it joined segments."""
    from yapit.gateway import audio_export

    def build(path: Path, fmt: str, chapters: list[Section]) -> list[int]:
        blocks_path = path.with_name(f"{path.name}.blocks")
        stored, marks = _store(blocks, chapters, blocks_path)
        try:
            return asyncio.run(
                audio_file.write_audio_file(
                    audio_export._pool(),
                    audio_export.WORKERS,
                    audio_export.ENCODINGS[audio_export.ExportFormat(fmt)],
                    blocks_path,
                    stored,
                    marks,
                    path,
                )
            )
        finally:
            blocks_path.unlink()

    return build


def _before(module, blocks: dict[str, bytes]):
    def build(path: Path, fmt: str, chapters: list[Section]) -> list[int]:
        old_chapters = [module.Chapter(title=c.title, variant_hashes=c.variant_hashes) for c in chapters]
        module.write_audio_file(path, module.ExportFormat(fmt), old_chapters, lambda hs: [blocks[h] for h in hs])
        return []

    return build


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("audio_export_before", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(args: Args, result: dict) -> None:
    line = {"selection": args.selection, "format": args.format, "cores": len(os.sched_getaffinity(0)), **result}
    print(json.dumps(line))
    if args.out:
        with args.out.open("a") as f:
            f.write(json.dumps(line) + "\n")


def corpus(speech: Path, selection: str, scratch: Path) -> tuple[dict[str, bytes], list[Section]]:
    """The selection's blocks by hash, and its sections; encoded once, then read from scratch."""
    cached = scratch / f"{selection}.pickle"
    if cached.exists():
        return pickle.loads(cached.read_bytes())
    spec = SELECTIONS[selection]
    rng = random.Random(0)
    weights = [rng.uniform(0.1, 1.9) for _ in range(spec["blocks"])]
    samples = [max(RATE // 2, round(w / sum(weights) * spec["seconds"] * RATE)) for w in weights]
    pcm = _decode(speech)
    blocks, hashes, at = {}, [], 0
    for i, n in enumerate(samples):
        piece = np.take(pcm, np.arange(at, at + n), mode="wrap")
        at = (at + n) % len(pcm)
        hashes.append(f"block-{i}")
        blocks[hashes[-1]] = _ogg_opus((piece * 32767).astype(np.int16))
    per_section = -(-len(hashes) // spec["sections"])
    chapters = [
        Section(title=f"Section {s + 1}", variant_hashes=hashes[first : first + per_section])
        for s, first in enumerate(range(0, len(hashes), per_section))
    ]
    cached.write_bytes(pickle.dumps((blocks, chapters)))
    return blocks, chapters


def _decode(source: Path | bytes, start: int = 0) -> np.ndarray:
    """Mono float PCM at RATE; a block is cut to the length it was encoded from, as the build cuts it."""
    container = av.open(io.BytesIO(source) if isinstance(source, bytes) else str(source))
    resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
    with container:
        frames = [f for frame in container.decode(audio=0) for f in resampler.resample(frame)]
    frames += resampler.resample(None)
    return np.concatenate([f.to_ndarray()[0] for f in frames])[start:]


def _ogg_opus(pcm: np.ndarray) -> bytes:
    """A block as the Kokoro worker encodes it (`_pcm_to_ogg_opus`)."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=RATE)
        stream.bit_rate = KOKORO_OPUS_BITRATE
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            out.mux(packet)
    return buf.getvalue()


def probe(path: Path) -> tuple[float, list[str]]:
    with av.open(str(path)) as container:
        assert container.duration is not None
        return container.duration / av.time_base, [c["metadata"]["title"] for c in container.chapters()]


def compare(path: Path, blocks: dict[str, bytes], chapters: list[Section], joins: list[int]) -> dict:
    """How far the file's decoded audio is from the blocks', in dB below the blocks' level, per 50 ms window.

    The reference is each block decoded on its own and the blocks laid end to end, scaled to the
    file's level (the stereo blocks reach MP3 3 dB quieter than AAC); the file is decoded and cut to
    its edit list's start. Reports the whole file's error, the worst window's, and the worst
    window's among those within 100 ms of a join.
    """
    reference = np.concatenate(
        [_decode(blocks[h])[: audio_file.block_samples(blocks[h])] for c in chapters for h in c.variant_hashes]
    )
    decoded = _decoded_file(path)
    n = min(len(reference), len(decoded))
    decoded, reference = decoded[:n].astype(np.float64), reference[:n].astype(np.float64)
    reference *= np.dot(decoded, reference) / np.dot(reference, reference)
    error = decoded - reference
    window = RATE // 20
    usable = n // window * window
    signal = np.square(reference[:usable]).reshape(-1, window).mean(axis=1)
    noise = np.square(error[:usable]).reshape(-1, window).mean(axis=1)
    loud = signal > 1e-4  # leave out silence, where any error is a large ratio of nothing
    db = 10 * np.log10(np.maximum(noise[loud], 1e-12) / signal[loud])
    near = np.zeros(len(signal), dtype=bool)
    for j in joins:
        near[max(0, (j - RATE // 10) // window) : (j + RATE // 10) // window + 1] = True
    near_loud = near[loud]
    return {
        "error_db": round(float(10 * np.log10(np.sum(np.square(error)) / np.sum(np.square(reference[:n])))), 1),
        "worst_window_db": round(float(db.max()), 1),
        "worst_join_window_db": round(float(db[near_loud].max()), 1) if near_loud.any() else None,
        "joins": len(joins),
    }


def _decoded_file(path: Path) -> np.ndarray:
    """The file's audio as a player plays it: the encoder's priming cut, by pts."""
    with av.open(str(path)) as container:
        frames = list(container.decode(audio=0))
    pcm = np.concatenate([f.to_ndarray()[0] for f in frames])
    first = frames[0].pts or 0
    return pcm[-first:] if first < 0 else pcm


def time_stages(module, fmt: str, chapters: list[Section], blocks: dict[str, bytes]) -> dict[str, float]:
    """Seconds per stage of one build by the older module, each stage run alone over the output of the one before."""
    encoding = module.ENCODINGS[module.ExportFormat(fmt)]
    audio = [blocks[h] for c in chapters for h in c.variant_hashes]
    stages: dict[str, float] = {}

    started = time.perf_counter()
    decoded = [frame for block in audio for frame in module._decode_block(block)]
    stages["decode"] = time.perf_counter() - started

    resampler = av.AudioResampler(format="fltp" if fmt == "m4b" else "s32p", layout="mono", rate=RATE)
    started = time.perf_counter()
    resampled = [f for frame in decoded for f in resampler.resample(frame)] + resampler.resample(None)
    stages["resample"] = time.perf_counter() - started

    with tempfile.TemporaryDirectory() as tmp:
        encoded = Path(tmp) / f"encoded.{fmt}"
        out = av.open(str(encoded), "w", format=encoding.container)
        stream = out.add_stream(encoding.codec, rate=RATE, layout="mono")
        assert isinstance(stream, av.AudioStream)
        stream.bit_rate = module.BIT_RATE
        written = 0
        started = time.perf_counter()
        for frame in resampled:
            frame.pts = written
            written += frame.samples
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
        out.close()
        stages["encode and mux"] = time.perf_counter() - started

        marks = [{"title": c.title, "start": 0, "end": 1} for c in chapters]
        started = time.perf_counter()
        module._remux_with_chapters(encoded, Path(tmp) / f"chaptered.{fmt}", encoding, marks)
        stages["remux with chapters"] = time.perf_counter() - started

    return {k: round(v, 3) for k, v in stages.items()}


def time_stages_after(fmt: str, chapters: list[Section], blocks: dict[str, bytes], scratch: Path) -> dict[str, float]:
    """Seconds per stage of the current build, as write_audio_file runs them, in processes a first build started."""
    from yapit.gateway import audio_export

    pool, encoding = audio_export._pool(), audio_export.ENCODINGS[audio_export.ExportFormat(fmt)]
    list(pool.map(abs, range(audio_export.WORKERS)))
    stages: dict[str, float] = {}
    blocks_path, path = scratch / "stages.blocks", scratch / f"stages.{fmt}"

    started = time.perf_counter()
    stored, marks = _store(blocks, chapters, blocks_path)
    stages["store blocks"] = time.perf_counter() - started

    segments = audio_file.plan_segments(stored, audio_export.WORKERS, audio_file._encoder(encoding).frame_size)
    outs = [scratch / f"stages.segment{k}" for k in range(len(segments))]
    started = time.perf_counter()
    futures = [pool.submit(audio_file.encode_segment, blocks_path, encoding, s, o) for s, o in zip(segments, outs)]
    encoded = [f.result() for f in futures]
    stages[f"encode {len(segments)} segments"] = time.perf_counter() - started

    started = time.perf_counter()
    pool.submit(audio_file.join_segments, encoding, encoded, marks, path).result()
    stages["join"] = time.perf_counter() - started

    for p in [blocks_path, path, *outs]:
        p.unlink()
    return {k: round(v, 3) for k, v in stages.items()}


if __name__ == "__main__":
    main(tyro.cli(Args, description=__doc__))
