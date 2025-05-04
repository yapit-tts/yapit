from typing import Final

AUDIO_KEY: Final[str] = "tts:audio:{hash}"
STREAM_CH: Final[str] = "tts:{hash}:stream"
DONE_CH: Final[str] = "tts:{hash}:done"
INFLIGHT_KEY: Final[str] = "tts:inflight:{hash}"
