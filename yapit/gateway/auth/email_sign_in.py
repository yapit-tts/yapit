import datetime as dt
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from yapit.gateway.auth.accounts import normalize_email, sign_in_by_email
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


class EmailTaken(Exception):
    """Another account already holds the address an email change asked for."""


class NotTheRequester(Exception):
    """An email change's link or code, used where the account that asked for the change is not signed in."""


def hash_code(challenge_id: uuid.UUID, code: str) -> str:
    # Salted with the challenge id, so no single table of the million code hashes reads every challenge at once.
    return hash_secret(f"{challenge_id}:{code}")


async def start_sign_in(db: AsyncSession, mailer: Mailer, settings: Settings, email: str, browser_nonce: str) -> None:
    """Mail a sign-in link and code to the address, whether or not an account holds it.

    `browser_nonce` is the secret of the browser that asked, kept in its pending cookie; a link
    opened where that cookie comes along signs in without a click. The challenge is committed only
    once the mail is out, so a failed send leaves nothing behind.
    """
    await _start(db, mailer, settings, normalize_email(email), browser_nonce, EmailChallengePurpose.sign_in, None)


async def start_email_change(
    db: AsyncSession, mailer: Mailer, settings: Settings, user_id: str, email: str, browser_nonce: str
) -> None:
    """Mail a link and code to the new address; the account's email switches only once one of them is used."""
    email = normalize_email(email)
    if (await db.exec(select(UserAccount).where(UserAccount.email == email))).first() is not None:
        raise EmailTaken
    await _start(db, mailer, settings, email, browser_nonce, EmailChallengePurpose.change_email, user_id)


async def _start(
    db: AsyncSession,
    mailer: Mailer,
    settings: Settings,
    email: str,
    browser_nonce: str,
    purpose: EmailChallengePurpose,
    user_id: str | None,
) -> None:
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
            purpose=purpose,
            user_id=user_id,
            token_hash=hash_secret(token),
            code_hash=hash_code(challenge_id, code),
            browser_nonce_hash=hash_secret(browser_nonce),
            created=now,
            expires=now + CHALLENGE_LIFETIME,
        )
    )
    await db.flush()
    await mailer.send(challenge_email(settings, purpose, email, token, code))
    await db.commit()


async def verify_sign_in_token(
    db: AsyncSession, token: str, *, browser_nonce: str | None, same_browser_only: bool, signed_in_user_id: str | None
) -> UserAccount | None:
    """Consume the challenge behind an emailed link and sign its account in.

    With `same_browser_only`, a browser whose nonce is not the challenge's gets OtherBrowser and consumes nothing.
    `signed_in_user_id` is who the request is signed in as, which an email change requires to be its requester.
    """
    challenge = (
        await db.exec(_live_challenges().where(EmailChallenge.token_hash == hash_secret(token)).with_for_update())
    ).first()
    if challenge is None:
        return None
    await _require_requester(db, challenge, signed_in_user_id)
    if same_browser_only and not _same_browser(challenge, browser_nonce):
        await db.rollback()
        raise OtherBrowser
    return await _complete(db, challenge)


async def _require_requester(db: AsyncSession, challenge: EmailChallenge, signed_in_user_id: str | None) -> None:
    """Refuse an email change anywhere but where its requester is signed in, consuming nothing.

    Otherwise whoever holds the new address, asked to confirm it, would move it onto the requester's
    account, and their own email sign-ins would land there from then on.
    """
    if challenge.purpose == EmailChallengePurpose.change_email and signed_in_user_id != challenge.user_id:
        await db.rollback()
        raise NotTheRequester


def _same_browser(challenge: EmailChallenge, browser_nonce: str | None) -> bool:
    return (
        browser_nonce is not None
        and challenge.browser_nonce_hash is not None
        and hmac.compare_digest(challenge.browser_nonce_hash, hash_secret(browser_nonce))
    )


async def verify_sign_in_code(
    db: AsyncSession, email: str, code: str, *, signed_in_user_id: str | None
) -> UserAccount | None:
    """Sign the account in if the code belongs to one of the address's live challenges; a miss costs each of them an attempt."""
    challenges = (
        await db.exec(_live_challenges().where(EmailChallenge.email == normalize_email(email)).with_for_update())
    ).all()
    for challenge in challenges:
        if hmac.compare_digest(challenge.code_hash, hash_code(challenge.id, code)):
            await _require_requester(db, challenge, signed_in_user_id)
            return await _complete(db, challenge)
    for challenge in challenges:
        challenge.attempts += 1
        db.add(challenge)
    await db.commit()
    return None


def _live_challenges():
    now = datetime.now(tz=dt.UTC)
    return select(EmailChallenge).where(
        col(EmailChallenge.consumed).is_(None),
        EmailChallenge.expires > now,
        EmailChallenge.attempts < MAX_CODE_ATTEMPTS,
    )


async def _complete(db: AsyncSession, challenge: EmailChallenge) -> UserAccount:
    """Consume the challenge and sign in its account: the one holding its address, created on first sign-in,
    or for an email change the one that asked, now holding the new address.
    """
    now = datetime.now(tz=dt.UTC)
    challenge.consumed = now
    db.add(challenge)
    match challenge.purpose:
        case EmailChallengePurpose.sign_in:
            account = await sign_in_by_email(db, challenge.email, now)
        case EmailChallengePurpose.change_email:
            assert challenge.user_id is not None
            account = await db.get_one(UserAccount, challenge.user_id)
            account.email = challenge.email
            account.last_sign_in = now
            db.add(account)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise EmailTaken
    return account


@dataclass(frozen=True)
class MailWording:
    subject: str
    action: str
    button: str
    code_where: str
    if_not_asked: str


MAIL_WORDING = {
    EmailChallengePurpose.sign_in: MailWording(
        subject="Sign in to Yapit",
        action="Open this link to sign in to Yapit",
        button="Sign in to Yapit",
        code_where="the sign-in page",
        if_not_asked="If you did not ask to sign in, ignore this email.",
    ),
    EmailChallengePurpose.change_email: MailWording(
        subject="Confirm your new email for Yapit",
        action="To make this your Yapit sign-in address, open this link in the browser where you are signed in to Yapit",
        button="Confirm this address",
        code_where="the account page",
        if_not_asked="If you did not ask for this change, ignore this email.",
    ),
}


def challenge_email(settings: Settings, purpose: EmailChallengePurpose, email: str, token: str, code: str) -> Email:
    fragment = {"token": token, "email": email}
    if purpose == EmailChallengePurpose.change_email:
        fragment["change"] = "1"
    # In the fragment, which browsers never send, the token stays out of every proxy's access log
    link = f"{settings.app_url.rstrip('/')}/auth/email#{urlencode(fragment)}"
    minutes = int(CHALLENGE_LIFETIME.total_seconds() // 60)
    words = MAIL_WORDING[purpose]
    text = (
        f"{words.action}:\n{link}\n\n"
        f"Or enter this code on {words.code_where}: {code}\n\n"
        f"The link and the code work once, within {minutes} minutes. {words.if_not_asked}"
    )
    html = (
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:10px 20px;border-radius:6px;'
        f'background:#4d8b5c;color:#ffffff;text-decoration:none;font-weight:600">{words.button}</a></p>'
        f"<p>Or enter this code on {words.code_where}: <strong>{code}</strong></p>"
        f"<p>The link and the code work once, within {minutes} minutes. {words.if_not_asked}</p>"
    )
    return Email(to=email, subject=words.subject, text=text, html=html)
