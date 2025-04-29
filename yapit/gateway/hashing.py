import hashlib


def calculate_audio_hash(text: str, model_id: str, voice_id: str, speed: float, codec: str) -> str:
    """Generates a unique hash for a given text block and synthesis parameters."""
    hasher = hashlib.sha256()
    hasher.update(text.encode("utf-8"))
    hasher.update(f"|{model_id}".encode("utf-8"))
    hasher.update(f"|{voice_id}".encode("utf-8"))
    hasher.update(f"|{speed:.2f}".encode("utf-8"))
    hasher.update(f"|{codec}".encode("utf-8"))
    return hasher.hexdigest()
