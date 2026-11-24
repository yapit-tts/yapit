import io

import av
import numpy as np

from yapit.contracts import KOKORO_OPUS_BITRATE

KOKORO_SAMPLE_RATE = 24_000

# The worker wrote stereo blocks before it wrote mono, and PyAV's mono-to-stereo upmix put each channel
# at 1/sqrt(2) of the PCM. Mono blocks are written at that level so they play as loud as those still cached.
CACHED_STEREO_LEVEL = 1 / np.sqrt(2)


def pcm_to_ogg_opus(pcm_bytes: bytes) -> bytes:
    """Encode raw 24kHz mono int16 PCM to mono OGG_OPUS."""
    if not pcm_bytes:
        return b""
    buf = io.BytesIO()
    output = av.open(buf, "w", format="ogg")
    stream = output.add_stream("libopus", rate=KOKORO_SAMPLE_RATE, layout="mono")
    stream.bit_rate = KOKORO_OPUS_BITRATE

    samples = np.round(np.frombuffer(pcm_bytes, dtype=np.int16) * CACHED_STEREO_LEVEL).astype(np.int16)
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = KOKORO_SAMPLE_RATE

    for packet in stream.encode(frame):
        output.mux(packet)
    for packet in stream.encode(None):
        output.mux(packet)
    output.close()

    return buf.getvalue()
