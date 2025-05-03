import hashlib
import math


def calculate_audio_hash(text: str, model_id: str, voice_id: str, speed: float, codec: str) -> str:
    """Generates a unique hash for a given text block and synthesis parameters."""
    hasher = hashlib.sha256()
    hasher.update(text.encode("utf-8"))
    hasher.update(f"|{model_id}".encode("utf-8"))
    hasher.update(f"|{voice_id}".encode("utf-8"))
    hasher.update(f"|{speed:.2f}".encode("utf-8"))
    hasher.update(f"|{codec}".encode("utf-8"))
    return hasher.hexdigest()


def estimate_duration_ms(text: str, speed: float = 1.0, chars_per_second: float = 15) -> int:
    """Estimate audio duration in milliseconds.

    Args:
        text (str): Text to be synthesized.
        speed (float): TTS speed multiplier (1.0 = normal).
        chars_per_second (float): Baseline CPS estimate at speed=1.0.
    """
    cps = chars_per_second * speed
    return math.ceil(len(text) / cps * 1000)
