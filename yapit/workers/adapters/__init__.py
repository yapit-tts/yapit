"""Synthesis adapters for different TTS models."""

from yapit.workers.adapters.base import SynthAdapter

__all__ = ["SynthAdapter"]

# Specific adapters are imported dynamically based on ADAPTER_CLASS environment variable
