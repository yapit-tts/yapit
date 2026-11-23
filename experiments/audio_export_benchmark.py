"""Time an audio export's build over blocks cut from a speech recording, and check the file it builds.

The blocks are what the Kokoro worker caches: 24 kHz mono speech as 48 kbps Ogg Opus, cut from any
recording PyAV reads at lengths drawn from a fixed seed, and kept in --scratch so every run builds
from the same bytes. A build is `write_audio_file` of `yapit/gateway/audio_export.py`, or of the
copy of an older one that --before names. Every built file is checked: duration equal to the
blocks' sum, one chapter per section, and the decoded audio compared with the blocks' own.

Examples:
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --runs 5
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --before old_audio_export.py --runs 5
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --selection ten-hours --format mp3
    uv run experiments/audio_export_benchmark.py --speech speech.mp3 --encoder-options aac_coder=twoloop
"""

import asyncio
import dataclasses
import importlib.util
import inspect
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

from yapit.contracts import KOKORO_OPUS_BITRATE
from yapit.gateway import audio_export

RATE = audio_export.SAMPLE_RATE
SELECTIONS = {
    # The build max timed on production: 5 min 10 s in 23 blocks, one section.
    "five-minutes": {"seconds": 310, "blocks": 23, "sections": 1},
    # A long audiobook: blocks of about the five-minute selection's mean length, 30 sections.
    "ten-hours": {"seconds": 36_000, "blocks": 2_700, "sections": 30},
}


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
    encoder_options: dict[str, str] | None = None
    """The encoder's options, as FFmpeg names them, instead of the ones the current build sets."""
    stages: bool = False
    """Time each stage of one build, run alone on one thread, instead of the whole build."""
    compare: bool = True
    """Decode each built file and compare it with the blocks' own audio."""
    scratch: Path = Path(tempfile.gettempdir()) / "audio-export-benchmark"
    """Where the blocks and the built files are kept."""
    out: Path | None = None
    """A file each run's result is appended to, as one JSON line."""


def main(args: Args) -> None:
    args.scratch.mkdir(parents=True, exist_ok=True)
    blocks, sections = corpus(args.speech, args.selection, args.scratch)
    audio_s = sum(_samples(b) for b in blocks.values()) / RATE
    fmt = args.format
    module = _load(args.before) if args.before else audio_export
    if args.encoder_options is not None:
        encoding = module.ENCODINGS[module.ExportFormat(fmt)]
        module.ENCODINGS[module.ExportFormat(fmt)] = dataclasses.replace(encoding, options=args.encoder_options)
    side = {"side": "before" if args.before else "after"}
    if not args.before:
        side["encoder_options"] = audio_export.ENCODINGS[audio_export.ExportFormat(fmt)].options
    print(f"{args.selection}: {len(blocks)} blocks, {len(sections)} sections, {audio_s:.1f} s of audio")

    if args.stages:
        stages = time_stages_before if args.before else time_stages
        report(args, {**side, "stages": stages(module, fmt, sections, blocks)})
        return
    path = args.scratch / f"build.{fmt}"
    for _ in range(args.runs):
        started = time.perf_counter()
        build(module, path, fmt, sections, blocks)
        wall = time.perf_counter() - started
        duration, titles = probe(path)
        result = {**side, "wall_s": round(wall, 3), "audio_s": round(audio_s, 3), "file_s": round(duration, 4)}
        result["ok"] = abs(duration - audio_s) < 0.001 and titles == [title for title, _ in sections]
        if args.compare:
            result |= compare(path, blocks, sections)
        report(args, result)


def build(module, path: Path, fmt: str, sections: list[tuple[str, list[str]]], blocks: dict[str, bytes]) -> None:
    """One build by the module, from the point its blocks' audio is fetched."""
    chapters = [module.Chapter(title=title, variant_hashes=hashes) for title, hashes in sections]
    if not inspect.iscoroutinefunction(module.write_audio_file):
        module.write_audio_file(path, module.ExportFormat(fmt), chapters, lambda hs: [blocks[h] for h in hs])
        return

    async def fetch(hashes: list[str]) -> list[bytes]:
        return [blocks[h] for h in hashes]

    async def no_progress(_: float) -> None:
        pass

    asyncio.run(module.write_audio_file(path, module.ExportFormat(fmt), chapters, fetch, no_progress))


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("audio_export_before", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _samples(block: bytes) -> int:
    """Samples at RATE in the PCM the block was encoded from."""
    head = block.find(b"OpusHead")
    return audio_export._encoded_samples(block, block[head : head + 19]) // 2


def report(args: Args, result: dict) -> None:
    line = {"selection": args.selection, "format": args.format, "cores": len(os.sched_getaffinity(0)), **result}
    print(json.dumps(line))
    if args.out:
        with args.out.open("a") as f:
            f.write(json.dumps(line) + "\n")


def corpus(speech: Path, selection: str, scratch: Path) -> tuple[dict[str, bytes], list[tuple[str, list[str]]]]:
    """The selection's blocks by hash, and its sections as (title, hashes); encoded once, then read from scratch."""
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
    sections = [
        (f"Section {s + 1}", hashes[first : first + per_section])
        for s, first in enumerate(range(0, len(hashes), per_section))
    ]
    cached.write_bytes(pickle.dumps((blocks, sections)))
    return blocks, sections


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


def compare(path: Path, blocks: dict[str, bytes], sections: list[tuple[str, list[str]]]) -> dict:
    """How far the file's decoded audio is from the blocks', in dB below the blocks' level.

    The reference is each block decoded on its own and the blocks laid end to end; the file is
    decoded, cut to its edit list's start and scaled to the reference's level. Reports the file's
    level against the reference's, the whole file's error, and the worst 50 ms window's.
    """
    reference = np.concatenate([_decode(blocks[h])[: _samples(blocks[h])] for _, hashes in sections for h in hashes])
    decoded = _decoded_file(path)
    n = min(len(reference), len(decoded))
    decoded, reference = decoded[:n].astype(np.float64), reference[:n].astype(np.float64)
    level = np.dot(decoded, reference) / np.dot(reference, reference)
    error = decoded / level - reference
    window = RATE // 20
    usable = n // window * window
    signal = np.square(reference[:usable]).reshape(-1, window).mean(axis=1)
    noise = np.square(error[:usable]).reshape(-1, window).mean(axis=1)
    loud = signal > 1e-4  # leave out silence, where any error is a large ratio of nothing
    db = 10 * np.log10(np.maximum(noise[loud], 1e-12) / signal[loud])
    return {
        "level_db": round(float(20 * np.log10(level)), 2),
        "error_db": round(float(10 * np.log10(np.sum(np.square(error)) / np.sum(np.square(reference[:n])))), 1),
        "worst_window_db": round(float(db.max()), 1),
    }


def _decoded_file(path: Path) -> np.ndarray:
    """The file's audio as a player plays it: the encoder's priming cut, by pts."""
    with av.open(str(path)) as container:
        frames = list(container.decode(audio=0))
    pcm = np.concatenate([f.to_ndarray()[0] for f in frames])
    first = frames[0].pts or 0
    return pcm[-first:] if first < 0 else pcm


def time_stages(module, fmt: str, sections: list[tuple[str, list[str]]], blocks: dict[str, bytes]) -> dict[str, float]:
    """Seconds per stage of one build, each stage run alone on one thread over the output of the one before."""
    encoding = module.ENCODINGS[module.ExportFormat(fmt)]
    audio = [blocks[h] for _, hashes in sections for h in hashes]
    stages: dict[str, float] = {}

    started = time.perf_counter()
    decoded = [module._decode_block(block) for block in audio]
    stages["decode, downmix and resample"] = time.perf_counter() - started

    with tempfile.TemporaryDirectory() as tmp:
        encoded = Path(tmp) / f"encoded.{fmt}"
        out = av.open(str(encoded), "w", format=encoding.container)
        stream = out.add_stream(encoding.codec, rate=RATE, layout="mono", options=encoding.options)
        assert isinstance(stream, av.AudioStream)
        stream.bit_rate = module.BIT_RATE
        stream.format = "fltp"
        written = 0
        started = time.perf_counter()
        for frame in decoded:
            frame.pts = written
            written += frame.samples
            out.mux(stream.encode(frame))
        out.mux(stream.encode(None))
        out.close()
        stages["encode and mux"] = time.perf_counter() - started

        marks = [{"title": title, "start": 0, "end": 1} for title, _ in sections]
        started = time.perf_counter()
        module._remux_with_chapters(encoded, Path(tmp) / f"chaptered.{fmt}", encoding, marks)
        stages["remux with chapters"] = time.perf_counter() - started

    return {k: round(v, 3) for k, v in stages.items()}


def time_stages_before(
    module, fmt: str, sections: list[tuple[str, list[str]]], blocks: dict[str, bytes]
) -> dict[str, float]:
    """Seconds per stage of one build by a module as on main, each stage run alone over the output of the one before."""
    encoding = module.ENCODINGS[module.ExportFormat(fmt)]
    audio = [blocks[h] for _, hashes in sections for h in hashes]
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

        marks = [{"title": title, "start": 0, "end": 1} for title, _ in sections]
        started = time.perf_counter()
        module._remux_with_chapters(encoded, Path(tmp) / f"chaptered.{fmt}", encoding, marks)
        stages["remux with chapters"] = time.perf_counter() - started

    return {k: round(v, 3) for k, v in stages.items()}


if __name__ == "__main__":
    main(tyro.cli(Args, description=__doc__))
