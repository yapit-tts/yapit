from pydantic import BaseModel


class ExtractedPage(BaseModel):
    """Single page extraction result."""

    index: int
    markdown: str  # full markdown including images (b64 if enabled)/tables/formulas


class OCRExtractionResult(BaseModel):
    """Complete OCR extraction result - provider agnostic."""

    pages: list[ExtractedPage]
    total_pages: int
    pages_processed: int

    # metadata
    document_type: str  # pdf, png, ...
    provider: str  # mistral, docling
    model: str  # mistral-ocr-latest, etc.
    processing_time_ms: int | None = None
