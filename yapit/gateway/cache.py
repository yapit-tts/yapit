import abc
import sqlite3
import time
from enum import StrEnum, auto
from pathlib import Path

import aiosqlite
from loguru import logger
from pydantic import BaseModel


class Caches(StrEnum):
    SQLITE = auto()


class CacheConfig(BaseModel):
    path: Path | str | None = None
    max_size_mb: int | None = None
    max_item_size_mb: int | None = None


class CacheStats(BaseModel):
    """Cache statistics for monitoring."""

    data_size_bytes: int  # Sum of all entry sizes
    file_size_bytes: int  # Actual DB file size on disk
    entry_count: int
    bloat_ratio: float  # file_size / data_size (1.0 = no bloat)


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

    @abc.abstractmethod
    async def get_stats(self) -> CacheStats:
        """Return cache statistics for monitoring."""

    @abc.abstractmethod
    async def vacuum_if_needed(self, bloat_threshold: float = 2.0) -> bool:
        """Vacuum the cache if bloat ratio exceeds threshold. Returns True if vacuumed."""


class SqliteCache(Cache):
    def __init__(self, config: CacheConfig):
        super().__init__(config)
        assert config.path is not None, "SqliteCache requires a path"
        self.db_path = Path(config.path) / "cache.db"
        self._max_size_bytes = config.max_size_mb * 1024 * 1024 if config.max_size_mb else None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize DB schema synchronously (only called once at startup)."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_cache_last_accessed ON cache(last_accessed)")
            db.execute("PRAGMA journal_mode=WAL")

    async def store(self, key: str, data: bytes) -> str | None:
        ts = time.time()
        size = len(data)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "REPLACE INTO cache(key, data, size, created_at, last_accessed) VALUES(?, ?, ?, ?, ?)",
                (key, data, size, ts, ts),
            )
            await db.commit()
        if self._max_size_bytes:
            await self._enforce_max_size()
        return key

    async def exists(self, key: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM cache WHERE key=?", (key,)) as cursor:
                row = await cursor.fetchone()
        return bool(row)

    async def retrieve_ref(self, key: str) -> str | None:
        return key if await self.exists(key) else None

    async def retrieve_data(self, key: str) -> bytes | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT data FROM cache WHERE key=?", (key,)) as cursor:
                row = await cursor.fetchone()
            if row:
                await db.execute("UPDATE cache SET last_accessed=? WHERE key=?", (time.time(), key))
                await db.commit()
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM cache WHERE key=?", (key,))
            await db.commit()
            return cursor.rowcount > 0

    async def _enforce_max_size(self) -> int:
        """Evict oldest entries (by last_accessed) until total size is under max_size_bytes."""
        if not self._max_size_bytes:
            return 0

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COALESCE(SUM(size), 0) FROM cache") as cursor:
                row = await cursor.fetchone()
                assert row is not None  # aggregate always returns a row
                total_size = row[0]

            if total_size <= self._max_size_bytes:
                return 0

            async with db.execute("SELECT key, size FROM cache ORDER BY last_accessed ASC") as cursor:
                rows = await cursor.fetchall()

            evicted = 0
            for key, size in rows:
                if total_size <= self._max_size_bytes:
                    break
                await db.execute("DELETE FROM cache WHERE key=?", (key,))
                total_size -= size
                evicted += 1

            if evicted > 0:
                await db.commit()
                logger.debug(f"Cache LRU eviction: removed {evicted} entries from {self.db_path}")

            return evicted

    async def get_stats(self) -> CacheStats:
        """Return cache statistics for monitoring."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COALESCE(SUM(size), 0), COUNT(*) FROM cache") as cursor:
                row = await cursor.fetchone()
                assert row is not None  # aggregate always returns a row
                data_size, entry_count = row[0], row[1]

        file_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        bloat_ratio = file_size / data_size if data_size > 0 else 1.0

        return CacheStats(
            data_size_bytes=data_size,
            file_size_bytes=file_size,
            entry_count=entry_count,
            bloat_ratio=bloat_ratio,
        )

    async def vacuum_if_needed(self, bloat_threshold: float = 2.0) -> bool:
        """Vacuum if file size exceeds bloat_threshold * data size."""
        stats = await self.get_stats()

        if stats.bloat_ratio <= bloat_threshold or stats.data_size_bytes == 0:
            return False

        logger.info(
            f"Cache vacuum starting: {self.db_path} "
            f"(bloat_ratio={stats.bloat_ratio:.2f}, file={stats.file_size_bytes / 1024 / 1024:.1f}MB, "
            f"data={stats.data_size_bytes / 1024 / 1024:.1f}MB)"
        )

        start = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("VACUUM")
            await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await db.commit()

        duration_ms = int((time.time() - start) * 1000)
        new_stats = await self.get_stats()

        logger.info(
            f"Cache vacuum complete: {self.db_path} "
            f"(duration={duration_ms}ms, new_size={new_stats.file_size_bytes / 1024 / 1024:.1f}MB, "
            f"reclaimed={(stats.file_size_bytes - new_stats.file_size_bytes) / 1024 / 1024:.1f}MB)"
        )

        return True
