"""Platform-wide constants for the gateway."""

import math

DEFAULT_CHARS_PER_SECOND = 14


def estimate_duration_ms(char_count: int) -> int:
    return math.ceil(char_count / DEFAULT_CHARS_PER_SECOND * 1000)


# MIME types that make sense for TTS use cases
# Processors should intersect their capabilities with these
SUPPORTED_DOCUMENT_MIME_TYPES = {
    # Text formats
    "text/html",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    # E-book formats
    "application/epub+zip",
    # Document formats
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "application/xhtml+xml",
    # Image formats
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}

# Formats that markitdown supports but we don't expose:
# - application/json (not useful for TTS)
# - text/csv (tabular data doesn't read well)
# - application/zip (too generic)

SUPPORTED_WEB_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
}
