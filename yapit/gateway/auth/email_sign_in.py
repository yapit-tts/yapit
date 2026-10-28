import datetime as dt
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.mailer import Email, Mailer
from yapit.gateway.auth.sessions import hash_secret, new_secret
from yapit.gateway.config import Settings
from yapit.gateway.domain_models import EmailChallenge, EmailChallengePurpose, UserAccount

CHALLENGE_LIFETIME = timedelta(minutes=15)
MAX_CODE_ATTEMPTS = 5
MAX_CHALLENGES_PER_ADDRESS = 3  # within one CHALLENGE_LIFETIME


class TooManyChallenges(Exception):
    pass


class OtherBrowser(Exception):
    """The link was opened in a browser other than the one that asked for it, so it waits for a click."""


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_code(challenge_id: uuid.UUID, code: str) -> str:
    # Salted with the challenge id: a million codes would otherwise hash to a million shared values.
    return hash_secret(f"{challenge_id}:{code}")


async def start_sign_in(db: AsyncSession, mailer: Mailer, settings: Settings, email: str, browser_nonce: str) -> None:
    """Mail a sign-in link and code to the address, whether or not an account holds it.

    `browser_nonce` is the secret of the browser that asked, kept in its pending cookie; a link
    opened where that cookie comes along signs in without a click. The challenge is committed only
    once the mail is out, so a failed send leaves nothing behind.
    """
    email = normalize_email(email)
    now = datetime.now(tz=dt.UTC)
    recent = (
        await db.exec(
            select(func.count())
            .select_from(EmailChallenge)
            .where(EmailChallenge.email == email, EmailChallenge.created > now - CHALLENGE_LIFETIME)
        )
    ).one()
    if recent >= MAX_CHALLENGES_PER_ADDRESS:
        raise TooManyChallenges

    token = new_secret()
    code = f"{secrets.randbelow(10**6):06d}"
    challenge_id = uuid.uuid4()
    db.add(
        EmailChallenge(
            id=challenge_id,
            email=email,
            purpose=EmailChallengePurpose.sign_in,
            token_hash=hash_secret(token),
            code_hash=hash_code(challenge_id, code),
            browser_nonce_hash=hash_secret(browser_nonce),
            created=now,
            expires=now + CHALLENGE_LIFETIME,
        )
    )
    await db.flush()
    await mailer.send(sign_in_email(settings, email, token, code))
    await db.commit()


async def verify_sign_in_token(
    db: AsyncSession, token: str, *, browser_nonce: str | None, same_browser_only: bool
) -> UserAccount | None:
    """Consume the challenge behind a sign-in link and sign its address in.

    With `same_browser_only`, a browser whose nonce is not the challenge's gets OtherBrowser and consumes nothing.
    """
    challenge = (
        await db.exec(_live_challenges().where(EmailChallenge.token_hash == hash_secret(token)).with_for_update())
    ).first()
    if challenge is None:
        return None
    if same_browser_only and not _same_browser(challenge, browser_nonce):
        await db.rollback()
        raise OtherBrowser
    return await _complete(db, challenge)


def _same_browser(challenge: EmailChallenge, browser_nonce: str | None) -> bool:
    return (
        browser_nonce is not None
        and challenge.browser_nonce_hash is not None
        and hmac.compare_digest(challenge.browser_nonce_hash, hash_secret(browser_nonce))
    )


async def verify_sign_in_code(db: AsyncSession, email: str, code: str) -> UserAccount | None:
    """Sign the address in if the code belongs to one of its live challenges; a miss costs each of them an attempt."""
    challenges = (
        await db.exec(_live_challenges().where(EmailChallenge.email == normalize_email(email)).with_for_update())
    ).all()
    for challenge in challenges:
        if hmac.compare_digest(challenge.code_hash, hash_code(challenge.id, code)):
            return await _complete(db, challenge)
    for challenge in challenges:
        challenge.attempts += 1
        db.add(challenge)
    await db.commit()
    return None


def _live_challenges():
    now = datetime.now(tz=dt.UTC)
    return select(EmailChallenge).where(
        EmailChallenge.purpose == EmailChallengePurpose.sign_in,
        col(EmailChallenge.consumed).is_(None),
        EmailChallenge.expires > now,
        EmailChallenge.attempts < MAX_CODE_ATTEMPTS,
    )


async def _complete(db: AsyncSession, challenge: EmailChallenge) -> UserAccount:
    """Consume the challenge and sign in the account holding its address, creating it on first sign-in."""
    now = datetime.now(tz=dt.UTC)
    challenge.consumed = now
    db.add(challenge)
    account = (
        await db.exec(
            insert(UserAccount)
            .values(id=str(uuid.uuid4()), email=challenge.email, created=now, last_sign_in=now)
            .on_conflict_do_update(index_elements=["email"], set_={"last_sign_in": now})
            .returning(UserAccount)
        )
    ).scalar_one()
    await db.commit()
    return account


def sign_in_email(settings: Settings, email: str, token: str, code: str) -> Email:
    # In the fragment, which browsers never send, the token stays out of every proxy's access log
    link = f"{settings.app_url.rstrip('/')}/auth/email#{urlencode({'token': token, 'email': email})}"
    minutes = int(CHALLENGE_LIFETIME.total_seconds() // 60)
    text = (
        f"Open this link to sign in to Yapit:\n{link}\n\n"
        f"Or enter this code on the sign-in page: {code}\n\n"
        f"The link and the code work once, within {minutes} minutes. "
        "If you did not ask to sign in, ignore this email."
    )
    html = (
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:10px 20px;border-radius:6px;'
        f'background:#4d8b5c;color:#ffffff;text-decoration:none;font-weight:600">Sign in to Yapit</a></p>'
        f"<p>Or enter this code on the sign-in page: <strong>{code}</strong></p>"
        f"<p>The link and the code work once, within {minutes} minutes. "
        "If you did not ask to sign in, ignore this email.</p>"
    )
    return Email(to=email, subject="Sign in to Yapit", text=text, html=html)
