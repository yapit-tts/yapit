"""Redis client construction for the gateway."""

import socket

import redis.asyncio as redis

# Connections here are long-lived and mostly idle, so a peer that vanishes without a FIN
# leaves reads hanging forever: nothing raises, so nothing retries or logs. Probe after
# 60s idle, every 10s, give up after 3 — a socket error in ~90s, which the loops around
# these connections already catch. Has to be TCP keepalive rather than socket_timeout:
# that is a read deadline on every command, and pubsub.listen() (unbounded) and
# yolo_client's brpop(timeout=120) legitimately outlast any value worth setting.
#
# These three are Linux names. The gateway only ever runs in a Linux container, but the
# test suite imports this module on the host, so absent options are skipped rather than
# raising at import; keepalive is still enabled, just with the OS defaults.
_KEEPALIVE = {
    opt: value
    for name, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3))
    if (opt := getattr(socket, name, None)) is not None
}


async def create_redis_client(redis_url: str) -> redis.Redis:
    return await redis.from_url(
        redis_url,
        decode_responses=False,
        socket_connect_timeout=5,
        socket_keepalive=True,
        socket_keepalive_options=_KEEPALIVE,
        health_check_interval=30,
    )
