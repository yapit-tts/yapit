"""Synthesis adapters for different TTS models."""

from yapit.workers.adapters.base import SynthAdapter
from yapit.workers.adapters.kokoro import KokoroAdapter

__all__ = ["SynthAdapter", "KokoroAdapter"]
