"""Platform-wide constants for the gateway."""

# MIME types that make sense for TTS use cases
# Processors should intersect their capabilities with these
PLATFORM_SUPPORTED_MIME_TYPES = {
    # Text formats
    "text/html",
    "text/plain",
    # E-book formats
    "application/epub+zip",
    # Document formats
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
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
