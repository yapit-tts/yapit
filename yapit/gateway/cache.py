import abc
import logging
import sqlite3
import time
from enum import StrEnum, auto
from pathlib import Path

from pydantic import BaseModel

log = logging.getLogger(__name__)


class Caches(StrEnum):
    SQLITE = auto()


class CacheConfig(BaseModel):
    path: Path | str | None = None  # only used if cache_type is fs or sqlite
    max_size_mb: int | None = None
    max_item_size_mb: int | None = None


class Cache(abc.ABC):
    def __init__(self, config: CacheConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def store(self, key: str, data: bytes, ttl_seconds: int | None = None) -> str | None:
        """Store `data` under `key` with optional TTL. Return cache_ref or None on failure."""

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


class SqliteCache(Cache):
    def __init__(self, config: CacheConfig):
        super().__init__(config)
        self.db_path = Path(config.path) / "cache.db"
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL  -- NULL means no expiration
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)")
            db.execute("PRAGMA journal_mode=WAL")  # enable Write-Ahead Logging for better concurrency

    async def store(self, key: str, data: bytes, ttl_seconds: int | None = None) -> str | None:
        ts = time.time()
        expires_at = ts + ttl_seconds if ttl_seconds else None
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "REPLACE INTO cache(key, data, created_at, expires_at) VALUES(?, ?, ?, ?)", (key, data, ts, expires_at)
            )
        return key

    async def exists(self, key: str) -> bool:
        current_time = time.time()
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT 1 FROM cache WHERE key=? AND (expires_at IS NULL OR expires_at > ?)", (key, current_time)
            ).fetchone()
        return bool(row)

    async def retrieve_ref(self, key: str) -> str | None:
        return key if await self.exists(key) else None

    async def retrieve_data(self, key: str) -> bytes | None:
        current_time = time.time()
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT data FROM cache WHERE key=? AND (expires_at IS NULL OR expires_at > ?)", (key, current_time)
            ).fetchone()
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as db:
            cur = db.execute("DELETE FROM cache WHERE key=?", (key,))
        return cur.rowcount > 0

    # TODO: never called
    async def vacuum(self) -> None:
        """Reclaim free space and defragment the DB. Also checkpoints the WAL into the main file."""
        with sqlite3.connect(self.db_path) as db:
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # TODO: never called
    async def cleanup_expired(self) -> int:
        """Remove expired entries."""
        current_time = time.time()
        with sqlite3.connect(self.db_path) as db:
            cur = db.execute("DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?", (current_time,))
        return cur.rowcount
