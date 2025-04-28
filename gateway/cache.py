import abc
import logging

from gateway.config import CacheConfig, get_settings

log = logging.getLogger(__name__)


class Cache(abc.ABC):
    def __init__(self, config: CacheConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def store(self, key: str, data: bytes) -> str | None:
        """Stores data bytes under the given key.

        Args:
            key: The unique identifier (audio_hash) for the data.
            data: The audio data bytes to store.

        Returns:
            A backend-specific reference (e.g., file path, S3 key) on success, or None on failure.
            This reference is stored in BlockVariant.cache_ref.
        """

    @abc.abstractmethod
    async def retrieve(self, key: str) -> bytes | None:
        """Retrieves data bytes for the given key.

        Args:
            key: The unique identifier (audio_hash) of the data to retrieve.

        Returns:
            The cached data bytes, or None if not found or on error.
        """

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Checks if data for a key exists in the cache.

        Args:
            key: The unique identifier (audio_hash) to check.

        Returns:
            True if the key exists, False otherwise.
        """

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Deletes data associated with the key.

        Args:
            key: The unique identifier (audio_hash) of the data to delete.

        Returns:
            True on successful deletion or if the key didn't exist,
            False on error.
        """


class NoOpCache(Cache):
    async def store(self, key: str, data: bytes) -> str | None:
        """Pretends to store data, returns a dummy reference."""
        return ""

    async def retrieve(self, key: str) -> bytes | None:
        """Always returns None, indicating data is not cached."""
        return None

    async def exists(self, key: str) -> bool:
        """Always returns False, indicating the key doesn't exist."""
        return False

    async def delete(self, key: str) -> bool:
        """Pretends to delete data, always returns True."""
        return True


CACHE_BACKENDS: dict[str, type[Cache]] = {
    "noop": NoOpCache,
    # "filesystem": FileSystemCache,
    # "s3": S3Cache,
}


def get_cache_backend() -> Cache:
    settings = get_settings()
    cache_type = settings.cache_type.lower()
    backend = CACHE_BACKENDS.get(cache_type)
    if backend:
        return backend(settings.cache_config)
    raise ValueError(f"Invalid cache backend type '{cache_type}'. Supported types: {', '.join(CACHE_BACKENDS.keys())}.")
