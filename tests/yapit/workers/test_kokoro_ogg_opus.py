import io

import av
import numpy as np
import pytest

from yapit.workers.kokoro.ogg_opus import KOKORO_SAMPLE_RATE, pcm_to_ogg_opus


def test_a_kokoro_block_is_mono_opus_at_32_kbps():
    seconds = 4
    # Noise, unlike a tone, takes every bit the encoder is allowed
    pcm = np.random.default_rng(0).normal(0, 4000, KOKORO_SAMPLE_RATE * seconds).astype(np.int16)

    block = pcm_to_ogg_opus(pcm.tobytes())

    with av.open(io.BytesIO(block)) as container:
        assert container.streams.audio[0].codec_context.channels == 1
    assert len(block) * 8 / seconds / 1000 == pytest.approx(32, abs=5)


def test_a_kokoro_block_plays_as_loud_as_one_cached_as_stereo():
    pcm = (np.sin(np.arange(KOKORO_SAMPLE_RATE * 2) * 0.09) * 8000).astype(np.int16)

    assert _played_level(pcm_to_ogg_opus(pcm.tobytes())) == pytest.approx(_played_level(_as_stereo(pcm)), rel=0.05)


def _as_stereo(pcm: np.ndarray) -> bytes:
    """The block as the worker wrote it before it wrote mono."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=KOKORO_SAMPLE_RATE, layout="stereo")
        stream.bit_rate = 48_000
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = KOKORO_SAMPLE_RATE
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            out.mux(packet)
    return buf.getvalue()


def _played_level(block: bytes) -> float:
    """RMS of a channel, as a player sends it to each speaker."""
    with av.open(io.BytesIO(block)) as container:
        channel = np.concatenate([frame.to_ndarray()[0] for frame in container.decode(audio=0)])
    return float(np.sqrt(np.mean(np.square(channel[len(channel) // 4 : -len(channel) // 4]))))
