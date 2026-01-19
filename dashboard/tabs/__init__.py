"""Dashboard tabs."""

from dashboard.tabs.detection import render as render_detection
from dashboard.tabs.extraction import render as render_extraction
from dashboard.tabs.overview import render as render_overview
from dashboard.tabs.reliability import render as render_reliability
from dashboard.tabs.tts import render as render_tts
from dashboard.tabs.usage import render as render_usage

__all__ = [
    "render_overview",
    "render_tts",
    "render_detection",
    "render_extraction",
    "render_reliability",
    "render_usage",
]
