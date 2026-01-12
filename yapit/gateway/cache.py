import abc
import sqlite3
import time
from enum import StrEnum, auto
from pathlib import Path

from pydantic import BaseModel


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
        self._max_size_bytes = config.max_size_mb * 1024 * 1024 if config.max_size_mb else None
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    expires_at REAL  -- NULL means no expiration
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_cache_last_accessed ON cache(last_accessed)")
            db.execute("PRAGMA journal_mode=WAL")

    async def store(self, key: str, data: bytes, ttl_seconds: int | None = None) -> str | None:
        ts = time.time()
        expires_at = ts + ttl_seconds if ttl_seconds else None
        size = len(data)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "REPLACE INTO cache(key, data, size, created_at, last_accessed, expires_at) VALUES(?, ?, ?, ?, ?, ?)",
                (key, data, size, ts, ts, expires_at),
            )
        if self._max_size_bytes:
            await self._enforce_max_size()
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
            if row:
                db.execute("UPDATE cache SET last_accessed=? WHERE key=?", (current_time, key))
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as db:
            cur = db.execute("DELETE FROM cache WHERE key=?", (key,))
        return cur.rowcount > 0

    async def _enforce_max_size(self) -> int:
        """Evict oldest entries (by last_accessed) until total size is under max_size_bytes.

        Returns number of entries evicted.
        """
        if not self._max_size_bytes:
            return 0

        with sqlite3.connect(self.db_path) as db:
            total_size = db.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]

            if total_size <= self._max_size_bytes:
                return 0

            # Delete oldest entries until under limit
            # Fetch all entries ordered by last_accessed, delete until we're under
            rows = db.execute("SELECT key, size FROM cache ORDER BY last_accessed ASC").fetchall()

            evicted = 0
            for key, size in rows:
                if total_size <= self._max_size_bytes:
                    break
                db.execute("DELETE FROM cache WHERE key=?", (key,))
                total_size -= size
                evicted += 1

            return evicted

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
