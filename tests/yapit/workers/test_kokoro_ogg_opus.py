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
