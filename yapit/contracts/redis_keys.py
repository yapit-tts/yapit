from typing import Final

TTS_AUDIO: Final[str] = "tts:audio:{hash}" # TODo add inline comment / desc.
TTS_STREAM: Final[str] = "tts:{hash}:stream"
TTS_DONE: Final[str] = "tts:{hash}:done"
TTS_INFLIGHT: Final[str] = "tts:inflight:{hash}" # redis NX lock

# one filter-job per document -- keyed by doc_id.
FILTER_STATUS:  Final[str] = "filters:{doc_id}:status"   # pending | running | done | error
FILTER_CANCEL:  Final[str] = "filters:{doc_id}:cancel"   # set -> worker aborts ASAP
FILTER_INFLIGHT:    Final[str] = "filters:{doc_id}:inflight" # redis NX lock
