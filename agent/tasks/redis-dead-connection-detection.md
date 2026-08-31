---
status: backlog
started: 2026-09-01
---

# Redis dead-connection detection

## Intent

The gateway builds every Redis client as `redis.from_url(url, decode_responses=False)`
and nothing else (`gateway/__init__.py`, `gateway/api_tts_dispatcher.py`,
`gateway/warm_cache.py`). redis-py's defaults then apply: `socket_timeout=None`,
`socket_keepalive=None`, `health_check_interval=0`.

So a peer that disappears without a FIN — an idle flow dropped by NAT, a container
pulled out from under a live connection — leaves reads hanging with no exception.
Nothing raises, so the loop around the await never retries and never logs. It affects
the visibility scanner, the billing consumer, the cache persister, the result consumer,
every WebSocket pubsub listener, and `yolo_client.wait_for_result`.

## Trigger

Pick this up when a consumer, scanner or pubsub listener is observed **silent** —
stopped doing its work with no corresponding error in the gateway log.

Deliberately not applied pre-emptively. The 30-day window ending 2026-08-30 contains
two Redis incidents (2026-07-31, 2026-08-02) and both surfaced loudly, as
`Connection closed by server` / `Connection refused` across three consumers at once.
The silent-hang mode is inferred from the client settings; it has never been observed.

## The trap

`socket_timeout` is the obvious fix and it is the wrong one. It is a read deadline on
every command, and two commands here legitimately block past any usable value:
`pubsub.listen()` (`gateway/api/v1/ws.py`) is unbounded, and
`yolo_client.wait_for_result` issues `brpop(timeout=120)`. Confirmed against a live
Redis — `socket_timeout=5` with `brpop(timeout=8)` raises `TimeoutError`.

TCP keepalive is the right layer: it detects a dead peer beneath the command, without
capping how long a healthy one may block.

## Prepared work

Branch `chore/redis-dead-connection-detection` (`7d75edd`, pushed, not merged). Adds a
`create_redis_client()` factory and routes all three construction sites through
`socket_keepalive=True` with `TCP_KEEPIDLE 60 / TCP_KEEPINTVL 10 / TCP_KEEPCNT 3`, so a
dead peer surfaces as a socket error in ~90s, plus `health_check_interval=30` for
connections that die while pooled. Type-checked and linted; the socket options were
verified as set on a live connection.

One thing to re-weigh before merging it: the branch also sets
`socket_connect_timeout=5`, which is the only line capable of newly breaking something,
since connects were previously unbounded.
