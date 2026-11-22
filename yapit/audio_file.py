"""An audio file built from a selection's Ogg Opus blocks: one AAC or MP3 stream, with a chapter per section.

The stream is encoded in segments, each by its own encoder in its own process, and the segments'
packets are joined into one stream. A join only sounds seamless where both encoders were fed the
same audio around it and chose the same window shapes there, so each segment's encoder starts
PRE_ROLL before its segment and runs LOOKAHEAD past the next segment's search window, and each
join sits at the quietest frame of that window.

This module imports nothing of the gateway's, so the processes that run it start light.
"""

import asyncio
import io
import itertools
import math
from collections.abc import Iterator
from concurrent.futures import Executor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import cast

import av
import numpy as np
from av.packet import PacketSideData, PktSideDataT, packet_sidedata_type_from_literal

SAMPLE_RATE = 24_000
BIT_RATE = 64_000
MIN_SEGMENT = 30 * SAMPLE_RATE
PRE_ROLL = SAMPLE_RATE
SEARCH = 2 * SAMPLE_RATE
LOOKAHEAD = SAMPLE_RATE
# Frames kept before a segment's search window, for the join to copy the main data the frame it
# joins at begins with. At 24 kHz and 64 kbps a frame holds about 180 bytes of it, and a frame's
# main data begins at most 255 bytes back, so two frames would do and four leave room; no test
# reaches a join that needs more than one.
RESERVOIR_FRAMES = 4
# The resampler's output is exact only from 32 samples after its first input and before its last.
RESAMPLER_MARGIN = 64


@dataclass(frozen=True)
class Encoding:
    container: str
    codec: str
    options: tuple[tuple[str, str], ...] = ()
    """The encoder's options, as FFmpeg names them."""


@dataclass(frozen=True)
class ChapterMark:
    """A chapter's title and its span, in samples of the stream."""

    title: str
    start: int
    end: int


@dataclass(frozen=True)
class Block:
    """A block's audio in the file the build stores the blocks in, and where its samples fall in the stream."""

    offset: int
    size: int
    start: int
    samples: int


@dataclass(frozen=True)
class Segment:
    """The stretch of the stream one encoder makes: the packets it keeps, and the wider stretch it encodes for its joins."""

    blocks: list[Block]
    encode_from: int
    encode_to: int
    keep_from: float
    keep_to: float
    search_from: int | None
    """Start of the window the join with the segment before is placed in; None for the first segment."""


@dataclass(frozen=True)
class EncodedSegment:
    path: Path
    packets: np.ndarray
    """Each packet's pts, duration and size, a row each, in the order they follow each other in path."""
    side_data: dict[int, list[tuple[PktSideDataT, bytes]]]
    """The side data of the packets that carry any, by pts: the encoder's delay on the first, its padding on the last."""
    loudness: dict[int, float]
    """Energy of the audio around each packet of the join's search window, by the packet's pts."""


def block_samples(audio: bytes) -> int:
    """Samples at SAMPLE_RATE in the PCM the block was encoded from, read from its Ogg pages without decoding it.

    FFmpeg's Ogg muxer, which wrote every block the Kokoro worker and the gateway cache, sets the
    last page's granule position to the PCM's length at 48 kHz plus twice the OpusHead's pre-skip.
    """
    last_page = _last_page(audio)
    granule = int.from_bytes(audio[last_page + 6 : last_page + 14], "little", signed=True)
    head = audio.find(b"OpusHead")
    pre_skip = int.from_bytes(audio[head + 10 : head + 12], "little")
    return (granule - 2 * pre_skip) // 2


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


async def write_audio_file(
    pool: Executor,
    workers: int,
    encoding: Encoding,
    blocks_path: Path,
    blocks: list[Block],
    chapters: list[ChapterMark],
    path: Path,
) -> list[int]:
    """Write the blocks stored in blocks_path as one stream into path, cut into `workers` segments encoded in the pool.

    Returns where the segments were joined, in samples.
    """
    segments = plan_segments(blocks, workers, _encoder(encoding).frame_size)
    outs = [path.with_name(f"{path.name}.segment{k}") for k in range(len(segments))]
    futures = []
    try:
        futures = [pool.submit(encode_segment, blocks_path, encoding, s, out) for s, out in zip(segments, outs)]
        encoded = await asyncio.gather(*map(asyncio.wrap_future, futures))
        return await asyncio.wrap_future(pool.submit(join_segments, encoding, encoded, chapters, path))
    finally:
        for future in futures:
            future.cancel()
        for out in outs:
            out.unlink(missing_ok=True)


def plan_segments(blocks: list[Block], workers: int, frame: int) -> list[Segment]:
    """Cut the stream into up to `workers` segments of at least MIN_SEGMENT, starting on the encoders' frame grid."""
    total = sum(b.samples for b in blocks)
    count = max(1, min(workers, total // MIN_SEGMENT))
    starts = [0, *(k * total // count // frame * frame for k in range(1, count)), total]
    pre_roll = -(-PRE_ROLL // frame) * frame
    segments = []
    for k in range(count):
        first, last = k == 0, k == count - 1
        encode_from = 0 if first else starts[k] - pre_roll
        encode_to = total if last else starts[k + 1] + SEARCH + LOOKAHEAD
        segments.append(
            Segment(
                blocks=[
                    b
                    for b in blocks
                    if b.start + b.samples > encode_from - RESAMPLER_MARGIN and b.start < encode_to + RESAMPLER_MARGIN
                ],
                encode_from=encode_from,
                encode_to=encode_to,
                keep_from=-math.inf if first else starts[k] - RESERVOIR_FRAMES * frame,
                keep_to=math.inf if last else starts[k + 1] + SEARCH,
                search_from=None if first else starts[k],
            )
        )
    return segments


def encode_segment(blocks_path: Path, encoding: Encoding, segment: Segment, out: Path) -> EncodedSegment:
    """Decode the segment's blocks and encode its stretch of the stream, writing the packets it keeps to out."""
    encoder = _encoder(encoding)
    resampler = av.AudioResampler(format=encoder.format, layout="mono", rate=SAMPLE_RATE)
    window = (
        (segment.search_from - encoder.frame_size, segment.search_from + SEARCH + 2 * encoder.frame_size)
        if segment.search_from is not None
        else (0, 0)
    )
    heard = np.zeros(window[1] - window[0], dtype=np.float64)
    packets, side_data = [], {}

    def keep(encoded: list[av.Packet]) -> None:
        for packet in encoded:
            assert packet.pts is not None
            if segment.keep_from <= packet.pts < segment.keep_to:
                f.write(bytes(packet))
                packets.append((packet.pts, packet.duration, packet.size))
                if attached := [(cast(PktSideDataT, d.data_type), bytes(d)) for d in packet.iter_sidedata()]:
                    side_data[packet.pts] = attached

    def encode(pcm: np.ndarray, at: int) -> None:
        lo, hi = max(at, segment.encode_from), min(at + pcm.shape[1], segment.encode_to)
        if lo >= hi:
            return
        pcm = pcm[:, lo - at : hi - at]
        w_lo, w_hi = max(lo, window[0]), min(hi, window[1])
        if w_lo < w_hi:
            heard[w_lo - window[0] : w_hi - window[0]] = pcm[0, w_lo - lo : w_hi - lo].astype(np.float64)
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(pcm), format=encoder.format.name, layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = lo
        frame.time_base = Fraction(1, SAMPLE_RATE)
        keep(encoder.encode(frame))

    at = segment.blocks[0].start if segment.blocks else 0
    with blocks_path.open("rb") as source, out.open("wb") as f:
        for block in [*segment.blocks, None]:
            if block is None:
                frames = resampler.resample(None)
            else:
                source.seek(block.offset)
                frames = [r for frame in _decode_block(source.read(block.size)) for r in resampler.resample(frame)]
            if frames:
                # One frame per block: the encoder's per-call overhead adds up over 20 ms frames
                pcm = np.concatenate([r.to_ndarray() for r in frames], axis=1)
                encode(pcm, at)
                at += pcm.shape[1]
        keep(encoder.encode(None))

    frame = encoder.frame_size
    loudness = {}
    if segment.search_from is not None:
        energy = np.square(heard)
        for pts, _, _ in packets:
            if segment.search_from <= pts < segment.search_from + SEARCH:
                lo = pts - frame - window[0]
                loudness[pts] = float(energy[max(0, lo) : lo + 3 * frame].sum())
    return EncodedSegment(
        path=out, packets=np.array(packets, dtype=np.int64).reshape(-1, 3), side_data=side_data, loudness=loudness
    )


def join_segments(
    encoding: Encoding, segments: list[EncodedSegment], chapters: list[ChapterMark], path: Path
) -> list[int]:
    """Write the segments' packets as one stream into path, each join at the quietest frame both sides can meet at."""
    joins = [_join(encoding, a, b) for a, b in itertools.pairwise(segments)]
    cuts = [-math.inf, *(cut for cut, _ in joins), math.inf]
    patches = {k: patch for k, (_, patch) in enumerate(joins)}

    out = av.open(str(path), "w", format=encoding.container)
    stream = out.add_stream(encoding.codec, rate=SAMPLE_RATE, layout="mono")
    assert isinstance(stream, av.AudioStream)
    stream.bit_rate = BIT_RATE
    out.set_chapters(
        [
            {
                "id": i + 1,
                "start": c.start,
                "end": c.end,
                "time_base": Fraction(1, SAMPLE_RATE),
                "metadata": {"title": c.title},
            }
            for i, c in enumerate(chapters)
        ]
    )
    time_base = Fraction(1, SAMPLE_RATE)
    for k, segment in enumerate(segments):
        patch = patches.get(k, {})
        for pts, duration, data in _read_packets(segment):
            if not cuts[k] <= pts < cuts[k + 1]:
                continue
            packet = av.Packet(patch.get(pts, data))
            packet.pts = packet.dts = pts
            packet.duration = duration
            packet.time_base = time_base
            for data_type, value in segment.side_data.get(pts, []):
                # PyAV's stub leaves out the constructor, which takes the type's number and the size
                attached = PacketSideData(packet_sidedata_type_from_literal(data_type), len(value))  # ty: ignore[too-many-positional-arguments]
                attached.update(value)
                attached.to_packet(packet, move=True)
            packet.stream = stream
            out.mux(packet)
    out.close()
    return [cut for cut, _ in joins]


def _join(encoding: Encoding, a: EncodedSegment, b: EncodedSegment) -> tuple[int, dict[int, bytes]]:
    """Where b takes over from a, and the bytes of a's packets before it that the join rewrites."""
    candidates = sorted(b.loudness, key=b.loudness.__getitem__)
    if encoding.codec != "libmp3lame":
        return candidates[0], {}
    a_packets, b_packets = dict(_tail(a, candidates)), dict(_tail(b, candidates))
    for cut in candidates:
        if (patch := _mp3_reservoir_patch(a_packets, b_packets, cut)) is not None:
            return cut, patch
    # No frame fits: b's quietest frame then begins with bytes of a's, and plays up to one frame of noise
    return candidates[0], {}


def _tail(segment: EncodedSegment, candidates: list[int]) -> Iterator[tuple[int, bytes]]:
    """The segment's packets from RESERVOIR_FRAMES before the first candidate to the last."""
    first, last = min(candidates), max(candidates)
    frame = int(segment.packets[1, 0] - segment.packets[0, 0])
    for pts, _, data in _read_packets(segment):
        if first - RESERVOIR_FRAMES * frame <= pts <= last:
            yield pts, data


def _mp3_reservoir_patch(a: dict[int, bytes], b: dict[int, bytes], cut: int) -> dict[int, bytes] | None:
    """A's frames before cut, rewritten so that b's frame at cut finds the main data it begins with in them.

    An MP3 frame's main data begins main_data_begin bytes back in the main data of the frames before
    it. Those of a's frames before cut that a's own frame at cut would have used are free for b's,
    so the join fits when b's frame needs no more of them than a's left.
    """
    if cut not in a or cut not in b:
        return None
    need, free = _main_data_begin(b[cut]), _main_data_begin(a[cut])
    if need > free:
        return None
    if need == 0:
        return {}
    b_before = _main_data_before(b, cut, need)
    a_before = _main_data_before(a, cut, need)
    if b_before is None or a_before is None:
        return None
    source = b"".join(b[pts][start:] for pts, start in b_before)[-need:]
    patch = {}
    for pts, start in reversed(a_before):
        frame = bytearray(a[pts])
        take = min(len(source), len(frame) - start)
        frame[len(frame) - take :] = source[len(source) - take :]
        source = source[: len(source) - take]
        patch[pts] = bytes(frame)
    return patch


def _main_data_before(frames: dict[int, bytes], cut: int, need: int) -> list[tuple[int, int]] | None:
    """The frames before cut whose main data holds the `need` bytes before it, as (pts, main data start), oldest first."""
    found, have = [], 0
    for pts in sorted((p for p in frames if p < cut), reverse=True):
        start = _main_data_start(frames[pts])
        found.append((pts, start))
        have += len(frames[pts]) - start
        if have >= need:
            return found[::-1]
    return None


def _main_data_start(frame: bytes) -> int:
    """Offset of an MP3 frame's main data: after its header, CRC and side information."""
    mpeg1, mono = (frame[1] >> 3) & 3 == 3, frame[3] >> 6 == 3
    crc = 0 if frame[1] & 1 else 2
    side = (17 if mono else 32) if mpeg1 else (9 if mono else 17)
    return 4 + crc + side


def _main_data_begin(frame: bytes) -> int:
    at = 4 + (0 if frame[1] & 1 else 2)
    if (frame[1] >> 3) & 3 == 3:
        return frame[at] << 1 | frame[at + 1] >> 7
    return frame[at]


def _read_packets(segment: EncodedSegment) -> Iterator[tuple[int, int, bytes]]:
    with segment.path.open("rb") as f:
        for pts, duration, size in segment.packets.tolist():
            yield pts, duration, f.read(size)


def _encoder(encoding: Encoding) -> av.AudioCodecContext:
    encoder = av.CodecContext.create(encoding.codec, "w")
    assert isinstance(encoder, av.AudioCodecContext)
    encoder.sample_rate = SAMPLE_RATE
    encoder.layout = "mono"
    # Float for both codecs: the downmix of the stereo blocks to integers would leave 3 dB of headroom
    encoder.format = "fltp"
    encoder.options = dict(encoding.options)
    encoder.bit_rate = BIT_RATE
    encoder.time_base = Fraction(1, SAMPLE_RATE)
    encoder.open()
    return encoder


def _decode_block(audio: bytes) -> Iterator[av.AudioFrame]:
    """A block's frames, cut to the length it was encoded from.

    FFmpeg's decoder leaves the encoder's end padding on a stream with a single audio page (a block
    under a second, such as a heading), which would put up to 13 ms of silence after it.
    """
    remaining = 2 * block_samples(audio)
    with av.open(io.BytesIO(audio), "r") as block:
        for frame in block.decode(block.streams.audio[0]):
            if remaining <= 0:
                break
            frame.pts = None
            if frame.samples > remaining:
                frame = _head(frame, remaining)
            remaining -= frame.samples
            yield frame


def _head(frame: av.AudioFrame, samples: int) -> av.AudioFrame:
    fifo = av.AudioFifo()
    fifo.write(frame)
    head = fifo.read(samples)
    assert head is not None
    return head
