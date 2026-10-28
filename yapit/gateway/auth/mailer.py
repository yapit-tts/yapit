import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from fastapi import Request
from loguru import logger

from yapit.gateway.config import Settings

SMTP_TIMEOUT_S = 15


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


class MailDeliveryError(Exception):
    pass


class Mailer(Protocol):
    async def send(self, email: Email) -> None:
        """Deliver the email or raise MailDeliveryError."""
        ...


class SmtpMailer:
    def __init__(self, host: str, port: int, username: str, password: str, sender: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender

    async def send(self, email: Email) -> None:
        try:
            await asyncio.to_thread(self._send, email)
        except (OSError, smtplib.SMTPException) as e:
            raise MailDeliveryError(f"SMTP delivery via {self.host}:{self.port} failed: {e!r}") from e

    def _send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")

        # Port 465 speaks TLS from the first byte; every other port must upgrade with STARTTLS,
        # so the credentials never cross the wire in the clear.
        if self.port == 465:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=SMTP_TIMEOUT_S)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_S)
        with smtp:
            if self.port != 465:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class LogMailer:
    """Stands in for SMTP when SMTP_HOST is empty: the message goes to the gateway log."""

    async def send(self, email: Email) -> None:
        logger.info(f"Email (SMTP_HOST unset, not sent) to {email.to}: {email.subject}\n{email.text}")


def create_mailer(settings: Settings) -> Mailer:
    if not settings.smtp_host:
        return LogMailer()
    return SmtpMailer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        sender=settings.smtp_sender,
    )


async def get_mailer(request: Request) -> Mailer:
    return request.app.state.mailer
