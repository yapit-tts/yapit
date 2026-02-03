"""Token reservation system for preventing billing race conditions.

Reservations hold estimated tokens when extraction starts, preventing users
from submitting more work than their balance allows. Actual billing happens
per-page as each page completes (via record_usage). Reservations are released
when extraction ends (success, partial, or cancel) since actual billing has
already occurred for all completed pages.

Storage: per-user Redis Hash at `reservations:{user_id}` with fields keyed
by content_hash and values as estimated token counts. O(1) create/release,
O(n) sum where n = user's active reservations (typically 0-2).
"""

from loguru import logger
from redis.asyncio import Redis

RESERVATION_TTL_SECONDS = 48 * 60 * 60  # 48 hours


def _reservations_key(user_id: str) -> str:
    return f"reservations:{user_id}"


async def create_reservation(
    redis: Redis,
    user_id: str,
    content_hash: str,
    estimated_tokens: int,
) -> None:
    key = _reservations_key(user_id)
    await redis.hset(key, content_hash, str(estimated_tokens))
    await redis.expire(key, RESERVATION_TTL_SECONDS)
    logger.info(f"Created reservation: user={user_id}, content_hash={content_hash[:8]}..., tokens={estimated_tokens}")


async def release_reservation(
    redis: Redis,
    user_id: str,
    content_hash: str,
) -> None:
    key = _reservations_key(user_id)
    removed = await redis.hdel(key, content_hash)
    if removed:
        logger.info(f"Released reservation: user={user_id}, content_hash={content_hash[:8]}...")


async def get_pending_reservations_total(redis: Redis, user_id: str) -> int:
    key = _reservations_key(user_id)
    values = await redis.hvals(key)
    return sum(int(v) for v in values)


async def get_reservation(redis: Redis, user_id: str, content_hash: str) -> int | None:
    key = _reservations_key(user_id)
    raw = await redis.hget(key, content_hash)
    return int(raw) if raw is not None else None
