"""Dashboard tabs."""

from dashboard.tabs.documents import render as render_documents
from dashboard.tabs.overview import render as render_overview
from dashboard.tabs.reliability import render as render_reliability
from dashboard.tabs.tts import render as render_tts
from dashboard.tabs.usage import render as render_usage

__all__ = [
    "render_overview",
    "render_tts",
    "render_documents",
    "render_reliability",
    "render_usage",
]
