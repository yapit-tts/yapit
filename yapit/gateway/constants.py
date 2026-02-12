"""Platform-wide constants for the gateway."""

import math

DEFAULT_CHARS_PER_SECOND = 14


def estimate_duration_ms(char_count: int) -> int:
    return math.ceil(char_count / DEFAULT_CHARS_PER_SECOND * 1000)


SUPPORTED_WEB_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
}
