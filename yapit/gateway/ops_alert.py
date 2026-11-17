"""Alerts by email to whoever runs this server (OPS_ALERT_EMAIL), for outages only they can end."""

import html

from loguru import logger
from redis.asyncio import Redis

from yapit.gateway.auth.mailer import Email, MailDeliveryError, Mailer

OPS_ALERT_COOLDOWN_S = 3600


async def send_ops_alert(redis: Redis, mailer: Mailer, to: str, key: str, subject: str, text: str) -> None:
    """Email the operator, at most once an hour per key.

    Every request that hits the outage calls this; the first one of the hour sends
    the mail and the rest return, so an outage pages once instead of once per page.
    """
    if not to:
        return
    if not await redis.set(f"ops_alert:{key}", b"1", nx=True, ex=OPS_ALERT_COOLDOWN_S):
        return
    try:
        await mailer.send(Email(to=to, subject=subject, text=text, html=f"<p>{html.escape(text)}</p>"))
    except MailDeliveryError as e:
        logger.error(f"Ops alert {key!r} not delivered: {e}")
