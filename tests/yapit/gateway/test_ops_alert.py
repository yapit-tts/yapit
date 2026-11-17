import pytest

from yapit.gateway.auth.mailer import Email, MailDeliveryError
from yapit.gateway.ops_alert import send_ops_alert


class FakeRedis:
    """Just enough of SET NX for the cooldown."""

    def __init__(self):
        self.keys: set[str] = set()

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys.add(key)
        return True


class RecordingMailer:
    def __init__(self, fail: bool = False):
        self.sent: list[Email] = []
        self.fail = fail

    async def send(self, email: Email) -> None:
        if self.fail:
            raise MailDeliveryError("smtp down")
        self.sent.append(email)


async def alert(redis, mailer, to="ops@example.com", key="ai-out-of-credit"):
    await send_ops_alert(redis, mailer, to, key=key, subject="AI down", text="top up <now>")


@pytest.mark.asyncio
async def test_outage_mails_once_per_cooldown():
    redis, mailer = FakeRedis(), RecordingMailer()

    for _ in range(12):
        await alert(redis, mailer)

    assert [e.to for e in mailer.sent] == ["ops@example.com"]
    assert mailer.sent[0].html == "<p>top up &lt;now&gt;</p>"


@pytest.mark.asyncio
async def test_each_key_has_its_own_cooldown():
    redis, mailer = FakeRedis(), RecordingMailer()

    await alert(redis, mailer, key="a")
    await alert(redis, mailer, key="b")

    assert len(mailer.sent) == 2


@pytest.mark.asyncio
async def test_no_recipient_sends_nothing():
    redis, mailer = FakeRedis(), RecordingMailer()

    await alert(redis, mailer, to="")

    assert mailer.sent == []
    assert redis.keys == set()


@pytest.mark.asyncio
async def test_failed_delivery_does_not_raise():
    await alert(FakeRedis(), RecordingMailer(fail=True))
