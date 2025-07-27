"""Synthesis adapters for different TTS models."""

from yapit.workers.adapters.base import SynthAdapter

__all__ = ["SynthAdapter"]

# Note: Specific adapters (like KokoroAdapter, HiggsAudioV2Adapter) are imported
# dynamically based on ADAPTER_CLASS environment variable to avoid unnecessary dependencies
