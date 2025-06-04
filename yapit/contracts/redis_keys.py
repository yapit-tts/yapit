from typing import Final

TTS_AUDIO: Final[str] = "tts:audio:{hash}"  # raw PCM/Opus bytes for a fully rendered block
TTS_DONE: Final[str] = "tts:{hash}:done"  # pubsub stream for completion notification
TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}"  # redis NX lock

# one filter-job per document -- keyed by document_id.
FILTER_STATUS: Final[str] = "filters:{document_id}:status"  # pending | running | done | error
FILTER_CANCEL: Final[str] = "filters:{document_id}:cancel"  # set -> worker aborts ASAP
FILTER_INFLIGHT: Final[str] = "filters:{document_id}:inflight"  # redis NX lock
