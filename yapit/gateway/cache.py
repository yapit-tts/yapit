import abc
import sqlite3
import time
from enum import StrEnum, auto
from pathlib import Path

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
    def get_stats(self) -> CacheStats:
        """Return cache statistics for monitoring."""

    @abc.abstractmethod
    async def vacuum_if_needed(self, bloat_threshold: float = 2.0) -> bool:
        """Vacuum the cache if bloat ratio exceeds threshold. Returns True if vacuumed."""


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
                    last_accessed REAL NOT NULL
                )
                """
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_cache_last_accessed ON cache(last_accessed)")
            db.execute("PRAGMA journal_mode=WAL")

    async def store(self, key: str, data: bytes) -> str | None:
        ts = time.time()
        size = len(data)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "REPLACE INTO cache(key, data, size, created_at, last_accessed) VALUES(?, ?, ?, ?, ?)",
                (key, data, size, ts, ts),
            )
        if self._max_size_bytes:
            await self._enforce_max_size()
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
            if row:
                db.execute("UPDATE cache SET last_accessed=? WHERE key=?", (time.time(), key))
        return row[0] if row else None

    async def delete(self, key: str) -> bool:
        with sqlite3.connect(self.db_path) as db:
            cur = db.execute("DELETE FROM cache WHERE key=?", (key,))
        return cur.rowcount > 0

    async def _enforce_max_size(self) -> int:
        """Evict oldest entries (by last_accessed) until total size is under max_size_bytes."""
        if not self._max_size_bytes:
            return 0

        with sqlite3.connect(self.db_path) as db:
            total_size = db.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]

            if total_size <= self._max_size_bytes:
                return 0

            rows = db.execute("SELECT key, size FROM cache ORDER BY last_accessed ASC").fetchall()

            evicted = 0
            for key, size in rows:
                if total_size <= self._max_size_bytes:
                    break
                db.execute("DELETE FROM cache WHERE key=?", (key,))
                total_size -= size
                evicted += 1

            if evicted > 0:
                logger.debug(f"Cache LRU eviction: removed {evicted} entries from {self.db_path}")

            return evicted

    def get_stats(self) -> CacheStats:
        """Return cache statistics for monitoring."""
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT COALESCE(SUM(size), 0), COUNT(*) FROM cache").fetchone()
            data_size = row[0]
            entry_count = row[1]

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
        stats = self.get_stats()

        if stats.bloat_ratio <= bloat_threshold or stats.data_size_bytes == 0:
            return False

        logger.info(
            f"Cache vacuum starting: {self.db_path} "
            f"(bloat_ratio={stats.bloat_ratio:.2f}, file={stats.file_size_bytes / 1024 / 1024:.1f}MB, "
            f"data={stats.data_size_bytes / 1024 / 1024:.1f}MB)"
        )

        start = time.time()
        with sqlite3.connect(self.db_path) as db:
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        duration_ms = int((time.time() - start) * 1000)
        new_stats = self.get_stats()

        logger.info(
            f"Cache vacuum complete: {self.db_path} "
            f"(duration={duration_ms}ms, new_size={new_stats.file_size_bytes / 1024 / 1024:.1f}MB, "
            f"reclaimed={(stats.file_size_bytes - new_stats.file_size_bytes) / 1024 / 1024:.1f}MB)"
        )

        return True
