import abc
import logging
import sqlite3
import time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)


class CacheConfig(BaseModel):
    dir: str | None = None  # only used if cache_type is fs or sqlite


class Cache(abc.ABC):
    def __init__(self, config: CacheConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def store(self, key: str, data: bytes) -> str | None:
        """Store `data` under `key`. Return cache_ref or None on failure."""

    @abc.abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if `key` is in cache, False otherwise."""

    @abc.abstractmethod
    async def retrieve_ref(self, key: str) -> str | None:
        """Return the cache_ref for `key`, or None if missing."""

    @abc.abstractmethod
    async def retrieve_data(self, key: str) -> bytes | None:
        """Return raw bytes for `key`, or None if missing."""

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete `key`. Return True if deleted or not present, False on error."""


class NoOpCache(Cache):
    async def store(self, key: str, data: bytes) -> str | None:
        return key

    async def exists(self, key: str) -> bool:
        return False

    async def retrieve_ref(self, key: str) -> str | None:
        return None

    async def retrieve_data(self, key: str) -> bytes | None:
        return None

    async def delete(self, key: str) -> bool:
        return True


class SqliteCache(Cache):
    def __init__(self, db_path: str, config: CacheConfig):
        super().__init__(config)
        self.db_path = Path(db_path) / "cache.db"
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            db.execute("PRAGMA journal_mode=WAL")  # enable Write-Ahead Logging for better concurrency

    async def store(self, key: str, data: bytes) -> str | None:
        ts = int(time.time())
        with sqlite3.connect(self.db_path) as db:
            db.execute("REPLACE INTO cache(key,data,created_at) VALUES(?,?,?)", (key, data, ts))
        return key

    async def exists(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT 1 FROM cache WHERE key=?", (key,)).fetchone()
        return bool(row)

    async def retrieve_ref(self, key: str) -> str | None:
        return key if await self.exists(key) else None

    async def retrieve_data(self, key: str) -> bytes | None:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT data FROM cache WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as db:
            cur = db.execute("DELETE FROM cache WHERE key=?", (key,))
        return cur.rowcount > 0

    async def vacuum(self) -> None:
        """Reclaim free space and defragment the DB. Also checkpoints the WAL into the main file."""
        with sqlite3.connect(self.db_path) as db:
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


CACHE_BACKENDS: dict[str, type[Cache]] = {
    "noop": NoOpCache,
    "sqlite": SqliteCache,
    # "filesystem": FileSystemCache,
    # "s3": S3Cache,
}


@lru_cache
def get_cache_backend() -> Cache:
    from yapit.gateway.config import get_settings

    settings = get_settings()
    cache_type = settings.cache_type.lower()
    backend = CACHE_BACKENDS.get(cache_type)
    if backend:
        return backend(settings.cache_config)
    raise ValueError(f"Invalid cache backend type '{cache_type}'. Supported types: {', '.join(CACHE_BACKENDS.keys())}.")
