import math

from yapit.gateway.domain_models import DocumentType


def estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 20) -> int:
    """Estimate audio duration in milliseconds. # TODO ... per model/voice est.?

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)


def detect_document_type(url: str, content_type: str | None = None) -> DocumentType:
    """Detect if URL points to a document or website.

    Args:
        url: The URL to check
        content_type: Optional Content-Type header from HTTP response

    Returns:
        DocumentType.document or DocumentType.website (defaults to website if unsure)
    """
    url_lower = url.lower()

    # Check URL patterns for documents
    doc_extensions = (".pdf", ".docx", ".doc", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".tiff")
    if any(url_lower.endswith(ext) for ext in doc_extensions):
        return DocumentType.document

    # todo: for e.g. arxiv we could replace /abs/ with /pdf/ automatically (not /html/ bcs not every paper has it)

    # Check Content-Type header
    if content_type:
        content_type_lower = content_type.lower()

        # Document MIME types
        doc_types = ("application/pdf", "image/", "application/msword", "application/vnd.openxmlformats-officedocument")
        if any(doc_type in content_type_lower for doc_type in doc_types):
            return DocumentType.document

        # Website MIME types
        if "text/html" in content_type_lower:
            return DocumentType.website

    # Default to website for all unclear cases
    return DocumentType.website
