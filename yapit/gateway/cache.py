import abc
import asyncio
import sqlite3
import time
from enum import StrEnum, auto
from pathlib import Path

import aiosqlite
from loguru import logger
from pydantic import BaseModel

LRU_FLUSH_INTERVAL_S = 10


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

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources. Called during shutdown."""


class SqliteCache(Cache):
    """SQLite-backed cache with dual connections (reader + writer) and batched LRU.

    Reader connection: pure reads (retrieve_data, exists, get_stats).
    WAL mode allows unlimited concurrent readers with zero writer contention.

    Writer connection: all mutations (store, delete, eviction, LRU flush, vacuum).
    Uses busy_timeout as safety net for any residual lock contention.

    LRU updates are batched: retrieve_data records accessed keys in memory,
    a background task flushes them to the DB every ~10s.
    """

    def __init__(self, config: CacheConfig):
        super().__init__(config)
        assert config.path is not None, "SqliteCache requires a path"
        self.db_path = Path(config.path) / "cache.db"
        self._max_size_bytes = config.max_size_mb * 1024 * 1024 if config.max_size_mb else None

        self._reader: aiosqlite.Connection | None = None
        self._writer: aiosqlite.Connection | None = None
        self._lru_pending: set[str] = set()
        self._lru_task: asyncio.Task | None = None
        self._closed = False

        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables synchronously at startup (idempotent)."""
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

    async def _get_reader(self) -> aiosqlite.Connection:
        if self._reader is None:
            self._reader = await aiosqlite.connect(self.db_path)
            await self._reader.execute("PRAGMA journal_mode=WAL")
        return self._reader

    async def _get_writer(self) -> aiosqlite.Connection:
        if self._writer is None:
            self._writer = await aiosqlite.connect(self.db_path)
            await self._writer.execute("PRAGMA journal_mode=WAL")
            await self._writer.execute("PRAGMA busy_timeout=5000")
        return self._writer

    def _ensure_lru_task(self) -> None:
        if self._lru_task is None or self._lru_task.done():
            self._lru_task = asyncio.create_task(self._lru_flush_loop())

    async def _lru_flush_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(LRU_FLUSH_INTERVAL_S)
            await self._flush_lru()

    async def _flush_lru(self) -> None:
        if not self._lru_pending:
            return
        keys = self._lru_pending.copy()
        self._lru_pending.clear()
        try:
            db = await self._get_writer()
            placeholders = ",".join("?" for _ in keys)
            await db.execute(
                f"UPDATE cache SET last_accessed=? WHERE key IN ({placeholders})",
                (time.time(), *keys),
            )
            await db.commit()
        except Exception:
            logger.exception(f"LRU flush failed for {self.db_path}")

    async def store(self, key: str, data: bytes) -> str | None:
        ts = time.time()
        db = await self._get_writer()
        await db.execute(
            "REPLACE INTO cache(key, data, size, created_at, last_accessed) VALUES(?, ?, ?, ?, ?)",
            (key, data, len(data), ts, ts),
        )
        await db.commit()
        if self._max_size_bytes:
            await self._enforce_max_size()
        return key

    async def exists(self, key: str) -> bool:
        db = await self._get_reader()
        async with db.execute("SELECT 1 FROM cache WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
        return bool(row)

    async def retrieve_ref(self, key: str) -> str | None:
        return key if await self.exists(key) else None

    async def retrieve_data(self, key: str) -> bytes | None:
        db = await self._get_reader()
        async with db.execute("SELECT data FROM cache WHERE key=?", (key,)) as cursor:
            row = await cursor.fetchone()
        if row:
            self._lru_pending.add(key)
            self._ensure_lru_task()
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        db = await self._get_writer()
        cursor = await db.execute("DELETE FROM cache WHERE key=?", (key,))
        await db.commit()
        return cursor.rowcount > 0

    async def _enforce_max_size(self) -> int:
        """Evict oldest entries (by last_accessed) until total size is under max_size_bytes."""
        if not self._max_size_bytes:
            return 0

        db = await self._get_writer()
        async with db.execute("SELECT COALESCE(SUM(size), 0) FROM cache") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            total_size = row[0]

        if total_size <= self._max_size_bytes:
            return 0

        excess = total_size - self._max_size_bytes
        async with db.execute("SELECT AVG(size) FROM cache") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            avg_size = row[0] or 1

        # Overshoot so the next few store() calls don't each re-trigger eviction
        estimate = int(excess / avg_size * 1.2) + 1

        cursor = await db.execute(
            "DELETE FROM cache WHERE key IN (SELECT key FROM cache ORDER BY last_accessed ASC LIMIT ?)",
            (estimate,),
        )
        evicted = cursor.rowcount
        await db.commit()
        return evicted

    async def get_stats(self) -> CacheStats:
        db = await self._get_reader()
        async with db.execute("SELECT COALESCE(SUM(size), 0), COUNT(*) FROM cache") as cursor:
            row = await cursor.fetchone()
            assert row is not None
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
        stats = await self.get_stats()

        if stats.bloat_ratio <= bloat_threshold or stats.data_size_bytes == 0:
            return False

        logger.info(
            f"Cache vacuum starting: {self.db_path} "
            f"(bloat_ratio={stats.bloat_ratio:.2f}, file={stats.file_size_bytes / 1024 / 1024:.1f}MB, "
            f"data={stats.data_size_bytes / 1024 / 1024:.1f}MB)"
        )

        start = time.time()
        db = await self._get_writer()
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

    async def close(self) -> None:
        self._closed = True
        if self._lru_task and not self._lru_task.done():
            self._lru_task.cancel()
            try:
                await self._lru_task
            except asyncio.CancelledError:
                pass
        await self._flush_lru()
        if self._reader:
            await self._reader.close()
        if self._writer:
            await self._writer.close()
