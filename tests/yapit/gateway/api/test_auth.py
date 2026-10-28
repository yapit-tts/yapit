"""Email sign-in, browser sessions and API tokens, through the gateway's API."""

import datetime as dt
import hashlib
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import WebSocketException
from loguru import logger
from sqlalchemy import event
from sqlmodel import delete, select, update
from starlette.websockets import WebSocket

from tests.yapit.gateway.api.conftest import (
    APP_URL,
    SAME_ORIGIN,
    SESSION_COOKIE,
    mailed_link,
    request_sign_in,
    settings_changed,
    sign_in,
    signed_in_user,
)
from yapit.gateway.auth import SELFHOST_USER, authenticate_ws, sign_anonymous_id
from yapit.gateway.auth.mailer import Email, MailDeliveryError, SmtpMailer
from yapit.gateway.auth.sessions import create_api_token
from yapit.gateway.db import get_engine
from yapit.gateway.domain_models import AuthSession, Document, EmailChallenge, UserAccount

THIRTY_DAYS_S = 30 * 24 * 3600
PENDING_COOKIE = "__Host-yapit_signin_pending"  # APP_URL is https


def set_cookie(response: httpx.Response, name: str) -> str:
    """The Set-Cookie header the response sends for this cookie."""
    return next(header for header in response.headers.get_list("set-cookie") if header.startswith(f"{name}="))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest_asyncio.fixture
async def api_token(session) -> str:
    """An API token of the user cli-user."""
    session.add(UserAccount(id="cli-user", email="cli@example.com"))
    await session.flush()
    token = create_api_token(session, "cli-user", "laptop")
    await session.commit()
    return token


# Signing in and out


@pytest.mark.asyncio
async def test_new_address_signs_up_by_link_and_stays_signed_in(browser, app):
    user = await sign_in(browser, app, "new@example.com")

    assert user["email"] == "new@example.com"
    assert await signed_in_user(browser) == user


@pytest.mark.asyncio
async def test_existing_account_signs_in_by_code_whatever_the_case_and_spacing_of_its_address(browser, app, session):
    session.add(UserAccount(id="0b5c5bd8-stack-auth-id", email="reader@example.com"))
    await session.commit()

    _, code = await request_sign_in(browser, app, "  Reader@Example.com ")
    response = await browser.post(
        "/v1/auth/email/verify", json={"email": "reader@example.com", "code": code}, headers=SAME_ORIGIN
    )

    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == "0b5c5bd8-stack-auth-id"
    assert (await signed_in_user(browser))["id"] == "0b5c5bd8-stack-auth-id"


@pytest.mark.asyncio
async def test_sign_out_revokes_the_session(browser, app):
    await sign_in(browser, app, "reader@example.com")
    cookie = browser.cookies[SESSION_COOKIE]

    response = await browser.post("/v1/auth/sign-out", headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert await signed_in_user(browser) is None
    browser.cookies.set(SESSION_COOKIE, cookie)
    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_sign_out_from_another_origin_is_refused(browser, app):
    user = await sign_in(browser, app, "reader@example.com")

    response = await browser.post("/v1/auth/sign-out", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert await signed_in_user(browser) == user


@pytest.mark.asyncio
async def test_signing_in_again_revokes_the_browsers_previous_session(browser, app):
    await sign_in(browser, app, "reader@example.com")
    first_cookie = browser.cookies[SESSION_COOKIE]

    await sign_in(browser, app, "other@example.com")

    browser.cookies.set(SESSION_COOKIE, first_cookie)
    assert await signed_in_user(browser) is None


# A link or code works once, within its lifetime, and wrong codes kill the challenge


@pytest.mark.asyncio
async def test_link_works_once(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    first = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)
    second = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_code_works_once(browser, app):
    _, code = await request_sign_in(browser, app, "reader@example.com")
    body = {"email": "reader@example.com", "code": code}

    first = await browser.post("/v1/auth/email/verify", json=body, headers=SAME_ORIGIN)
    second = await browser.post("/v1/auth/email/verify", json=body, headers=SAME_ORIGIN)

    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_link_and_code_expire_after_15_minutes(browser, app, session):
    token, code = await request_sign_in(browser, app, "reader@example.com")
    challenge = (await session.exec(select(EmailChallenge))).one()
    assert challenge.expires - challenge.created == timedelta(minutes=15)
    sixteen_minutes_ago = datetime.now(tz=dt.UTC) - timedelta(minutes=16)
    await session.exec(
        update(EmailChallenge).values(created=sixteen_minutes_ago, expires=sixteen_minutes_ago + timedelta(minutes=15))
    )
    await session.commit()

    by_link = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)
    by_code = await browser.post(
        "/v1/auth/email/verify", json={"email": "reader@example.com", "code": code}, headers=SAME_ORIGIN
    )

    assert by_link.status_code == 400
    assert by_code.status_code == 400


def wrong_code(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


@pytest.mark.asyncio
async def test_right_code_after_four_wrong_ones_signs_in(browser, app):
    _, code = await request_sign_in(browser, app, "reader@example.com")
    for _ in range(4):
        response = await browser.post(
            "/v1/auth/email/verify", json={"email": "reader@example.com", "code": wrong_code(code)}, headers=SAME_ORIGIN
        )
        assert response.status_code == 400

    response = await browser.post(
        "/v1/auth/email/verify", json={"email": "reader@example.com", "code": code}, headers=SAME_ORIGIN
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_fifth_wrong_code_kills_the_challenge(browser, app):
    token, code = await request_sign_in(browser, app, "reader@example.com")
    for _ in range(5):
        await browser.post(
            "/v1/auth/email/verify", json={"email": "reader@example.com", "code": wrong_code(code)}, headers=SAME_ORIGIN
        )

    by_code = await browser.post(
        "/v1/auth/email/verify", json={"email": "reader@example.com", "code": code}, headers=SAME_ORIGIN
    )
    by_link = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    assert by_code.status_code == 400
    assert by_link.status_code == 400


# "Email me a sign-in link" answers the same whether or not the address has an account


@pytest.mark.asyncio
async def test_start_answers_alike_for_known_and_unknown_addresses(browser, session):
    session.add(UserAccount(id="known-user", email="known@example.com"))
    await session.commit()

    known = await browser.post("/v1/auth/email/start", json={"email": "known@example.com"})
    unknown = await browser.post("/v1/auth/email/start", json={"email": "unknown@example.com"})

    assert (known.status_code, known.content) == (unknown.status_code, unknown.content)
    assert sorted(known.headers.keys()) == sorted(unknown.headers.keys())


@pytest.mark.asyncio
async def test_fourth_sign_in_email_to_an_address_within_15_minutes_is_refused(browser, app):
    for _ in range(3):
        await request_sign_in(browser, app, "reader@example.com")

    fourth = await browser.post("/v1/auth/email/start", json={"email": "Reader@example.com"})
    other_address = await browser.post("/v1/auth/email/start", json={"email": "other@example.com"})

    assert fourth.status_code == 429
    assert other_address.status_code == 202


@pytest.mark.asyncio
async def test_sign_in_emails_older_than_15_minutes_stop_counting(browser, app, session):
    for _ in range(3):
        await request_sign_in(browser, app, "reader@example.com")
    sixteen_minutes_ago = datetime.now(tz=dt.UTC) - timedelta(minutes=16)
    await session.exec(update(EmailChallenge).values(created=sixteen_minutes_ago))
    await session.commit()

    response = await browser.post("/v1/auth/email/start", json={"email": "reader@example.com"})

    assert response.status_code == 202


# Secrets are stored only as SHA-256 hashes


@pytest.mark.asyncio
async def test_link_token_code_and_session_token_are_stored_only_as_hashes(browser, app, session):
    token, code = await request_sign_in(browser, app, "reader@example.com")
    challenge = (await session.exec(select(EmailChallenge))).one()
    assert challenge.token_hash == sha256(token)
    assert token not in repr(challenge.model_dump())
    assert not re.search(rf"\b{code}\b", repr(challenge.model_dump()))

    await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)
    cookie = browser.cookies[SESSION_COOKIE]
    stored = (await session.exec(select(AuthSession))).one()
    assert stored.token_hash == sha256(cookie)
    assert cookie not in repr(stored.model_dump())


@pytest.mark.asyncio
async def test_api_token_is_stored_only_as_its_hash(api_token, session):
    stored = (await session.exec(select(AuthSession))).one()

    assert api_token.startswith("yapit_")
    assert stored.token_hash == sha256(api_token)
    assert api_token not in repr(stored.model_dump())


# The link and the browser that asked for it


@pytest.mark.asyncio
async def test_link_carries_its_token_in_the_fragment_only(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    link = urlsplit(mailed_link(app))

    assert link.path == "/auth/email"
    assert link.query == ""
    assert parse_qs(link.fragment) == {"token": [token], "email": ["reader@example.com"]}


@pytest.mark.asyncio
async def test_start_sets_an_httponly_pending_cookie(browser):
    response = await browser.post("/v1/auth/email/start", json={"email": "reader@example.com"})

    assert "HttpOnly" in set_cookie(response, PENDING_COOKIE)


@pytest.mark.asyncio
async def test_link_opened_in_the_browser_that_asked_signs_in_without_a_click(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    response = await browser.post(
        "/v1/auth/email/verify", json={"token": token, "same_browser_only": True}, headers=SAME_ORIGIN
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "reader@example.com"
    assert PENDING_COOKIE not in browser.cookies


@pytest.mark.asyncio
async def test_link_opened_in_another_browser_waits_for_a_click_and_consumes_nothing(browser, app, real_auth):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as other_browser:
        automatic = await other_browser.post(
            "/v1/auth/email/verify", json={"token": token, "same_browser_only": True}, headers=SAME_ORIGIN
        )
        clicked = await other_browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    assert automatic.status_code == 409
    assert clicked.status_code == 200


@pytest.mark.asyncio
async def test_every_link_a_browser_asked_for_signs_it_in_without_a_click(browser, app):
    first_token, _ = await request_sign_in(browser, app, "reader@example.com")
    await request_sign_in(browser, app, "reader@example.com")

    response = await browser.post(
        "/v1/auth/email/verify", json={"token": first_token, "same_browser_only": True}, headers=SAME_ORIGIN
    )

    assert response.status_code == 200


# The session cookie


@pytest.mark.asyncio
async def test_session_cookie_flags(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    response = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    cookie = set_cookie(response, SESSION_COOKIE)
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Secure" in cookie
    assert f"Max-Age={THIRTY_DAYS_S}" in cookie


@pytest.mark.asyncio
async def test_session_cookie_is_not_secure_on_a_plain_http_app(app, real_auth):
    with settings_changed(app, app_url="http://localhost:5173"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:5173"
        ) as browser:
            token, _ = await request_sign_in(browser, app, "reader@example.com")
            response = await browser.post(
                "/v1/auth/email/verify", json={"token": token}, headers={"Origin": "http://localhost:5173"}
            )

    assert response.status_code == 200
    assert "Secure" not in set_cookie(response, "yapit_session")


async def set_session_expiry(session, days_left: float) -> datetime:
    expires = datetime.now(tz=dt.UTC) + timedelta(days=days_left)
    await session.exec(update(AuthSession).values(expires=expires))
    await session.commit()
    return expires


async def stored_expiry(session) -> datetime:
    session.expire_all()
    expires = (await session.exec(select(AuthSession))).one().expires
    assert expires is not None
    return expires


@pytest.mark.asyncio
async def test_session_with_under_15_days_left_is_extended_to_30(browser, app, session):
    await sign_in(browser, app, "reader@example.com")
    await set_session_expiry(session, days_left=14)

    response = await browser.get("/v1/users/me/preferences")

    assert response.status_code == 200
    assert abs((await stored_expiry(session)) - (datetime.now(tz=dt.UTC) + timedelta(days=30))) < timedelta(minutes=1)
    max_age = re.search(r"Max-Age=(\d+)", response.headers["set-cookie"])
    assert max_age is not None and THIRTY_DAYS_S - int(max_age.group(1)) < 60


@pytest.mark.asyncio
async def test_session_with_over_15_days_left_keeps_its_expiry(browser, app, session):
    await sign_in(browser, app, "reader@example.com")
    expires = await set_session_expiry(session, days_left=16)

    response = await browser.get("/v1/users/me/preferences")

    assert response.status_code == 200
    assert await stored_expiry(session) == expires
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_expired_session_signs_nobody_in(browser, app, session):
    await sign_in(browser, app, "reader@example.com")
    await set_session_expiry(session, days_left=-1)

    assert await signed_in_user(browser) is None
    assert (await browser.get("/v1/users/me/preferences")).status_code == 401


# Cookie-authenticated state changes only from the app's origin


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (SAME_ORIGIN, 200),
        ({"Origin": "https://evil.example"}, 403),
        ({}, 403),
    ],
)
async def test_cookie_authenticated_state_change_needs_the_app_origin(browser, app, headers, expected):
    await sign_in(browser, app, "reader@example.com")

    response = await browser.patch("/v1/users/me/preferences", json={"pinned_voices": ["a"]}, headers=headers)

    assert response.status_code == expected


@pytest.mark.asyncio
async def test_cookie_authenticated_read_from_another_origin_is_allowed(browser, app):
    await sign_in(browser, app, "reader@example.com")

    response = await browser.get("/v1/users/me/preferences", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_sign_in_from_another_origin_is_refused(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    response = await browser.post(
        "/v1/auth/email/verify", json={"token": token}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert SESSION_COOKIE not in browser.cookies


# API tokens


@pytest.mark.asyncio
async def test_api_token_authenticates_without_an_origin(app, real_auth, api_token):
    token = api_token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": f"Bearer {token}"}
    ) as cli:
        changed = await cli.patch("/v1/users/me/preferences", json={"pinned_voices": ["a"]})
        whoami = await cli.get("/v1/auth/session")

    assert changed.status_code == 200
    assert whoami.json()["user"]["id"] == "cli-user"


@pytest.mark.asyncio
async def test_browser_session_token_is_not_an_api_token(browser, app):
    await sign_in(browser, app, "reader@example.com")
    cookie = browser.cookies[SESSION_COOKIE]
    browser.cookies.clear()

    response = await browser.get("/v1/users/me/preferences", headers={"Authorization": f"Bearer {cookie}"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_token_is_not_a_session_cookie(browser, api_token):
    browser.cookies.set(SESSION_COOKIE, api_token)

    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_session_answers_signed_out_to_an_unknown_api_token(app, real_auth):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": "Bearer yapit_nope"}
    ) as cli:
        response = await cli.get("/v1/auth/session")

    assert response.status_code == 200
    assert response.json()["user"] is None


@pytest.mark.asyncio
async def test_unknown_api_token_is_refused(app, real_auth):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": "Bearer yapit_nope"}
    ) as cli:
        response = await cli.get("/v1/users/me/preferences")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_token_created_in_settings_authenticates_until_revoked(browser, app):
    await sign_in(browser, app, "reader@example.com")

    created = await browser.post("/v1/auth/tokens", json={"label": " laptop "}, headers=SAME_ORIGIN)
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": f"Bearer {token}"}
    ) as cli:
        before = (await cli.get("/v1/auth/session")).json()["user"]
        listed = (await browser.get("/v1/auth/tokens")).json()
        revoked = await browser.delete(f"/v1/auth/tokens/{created.json()['id']}", headers=SAME_ORIGIN)
        after = (await cli.get("/v1/auth/session")).json()["user"]

    assert token.startswith("yapit_")
    assert before["email"] == "reader@example.com"
    assert [t["label"] for t in listed] == ["laptop"]
    assert token not in str(listed)
    assert revoked.status_code == 204
    assert after is None


@pytest.mark.asyncio
async def test_api_tokens_of_another_user_are_neither_listed_nor_revocable(browser, app, api_token):
    await sign_in(browser, app, "reader@example.com")

    listed = (await browser.get("/v1/auth/tokens")).json()
    revoked = await browser.delete(f"/v1/auth/tokens/{sha256(api_token)}", headers=SAME_ORIGIN)

    assert listed == []
    assert revoked.status_code == 404


@pytest.mark.asyncio
async def test_api_token_list_leaves_out_browser_sessions(browser, app):
    await sign_in(browser, app, "reader@example.com")

    revoked = await browser.delete(f"/v1/auth/tokens/{sha256(browser.cookies[SESSION_COOKIE])}", headers=SAME_ORIGIN)

    assert (await browser.get("/v1/auth/tokens")).json() == []
    assert revoked.status_code == 404
    assert await signed_in_user(browser) is not None


@pytest.mark.asyncio
async def test_anonymous_user_gets_no_api_token(app, real_auth, _test_settings):
    headers = {
        "X-Anonymous-ID": "a1",
        "X-Anonymous-Token": sign_anonymous_id("a1", _test_settings.anonymous_session_secret),
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as client:
        response = await client.post("/v1/auth/tokens", json={"label": "x"}, headers=headers)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("signed_for", "expected"),
    [("a1", 200), ("a2", 401), (None, 401)],
)
async def test_anonymous_session_needs_the_token_signed_for_its_id(
    app, real_auth, _test_settings, signed_for, expected
):
    headers = {"X-Anonymous-ID": "a1"}
    if signed_for is not None:
        headers["X-Anonymous-Token"] = sign_anonymous_id(signed_for, _test_settings.anonymous_session_secret)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as client:
        response = await client.get("/v1/users/me/preferences", headers=headers)

    assert response.status_code == expected


# Name and email, from account settings


@pytest.mark.asyncio
async def test_name_is_set_and_cleared(browser, app):
    await sign_in(browser, app, "reader@example.com")

    named = await browser.patch("/v1/users/me", json={"name": "  Ada  "}, headers=SAME_ORIGIN)
    name_after_set = (await signed_in_user(browser))["name"]
    cleared = await browser.patch("/v1/users/me", json={"name": ""}, headers=SAME_ORIGIN)

    assert (named.status_code, cleared.status_code) == (204, 204)
    assert name_after_set == "Ada"
    assert (await signed_in_user(browser))["name"] is None


async def request_email_change(browser, app, new_email: str) -> tuple[str, str]:
    response = await browser.post("/v1/auth/email/change", json={"email": new_email}, headers=SAME_ORIGIN)
    assert response.status_code == 202, response.text
    mail: Email = app.state.mailer.sent[-1]
    assert mail.to == new_email.lower()
    token = parse_qs(urlsplit(mailed_link(app)).fragment)["token"][0]
    code = re.search(r"\b\d{6}\b", mail.text)
    assert code is not None
    return token, code.group()


@pytest.mark.asyncio
async def test_email_changes_only_once_the_link_sent_to_the_new_address_is_opened(browser, app):
    user = await sign_in(browser, app, "old@example.com")

    token, _ = await request_email_change(browser, app, "new@example.com")
    before = await signed_in_user(browser)
    confirmed = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    assert before["email"] == "old@example.com"
    assert confirmed.status_code == 200, confirmed.text
    assert await signed_in_user(browser) == {**user, "email": "new@example.com"}
    await browser.post("/v1/auth/sign-out", headers=SAME_ORIGIN)
    assert (await sign_in(browser, app, "new@example.com"))["id"] == user["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("by", ["link", "code"])
@pytest.mark.parametrize("holder_account", [None, "holder-elsewhere@example.com"])
async def test_email_change_used_where_its_requester_is_not_signed_in_changes_nothing(browser, app, by, holder_account):
    """Whoever holds the new address, signed out or signed in to an account of their own,
    cannot pull it into the requester's account by confirming the mail.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as holder:
        holder_user = await sign_in(holder, app, holder_account) if holder_account else None
        user = await sign_in(browser, app, "requester@example.com")
        token, code = await request_email_change(browser, app, "holder@example.com")
        body = {"token": token} if by == "link" else {"email": "holder@example.com", "code": code}

        refused = await holder.post("/v1/auth/email/verify", json=body, headers=SAME_ORIGIN)
        holder_user_after = await signed_in_user(holder)
    confirmed_by_requester = await browser.post("/v1/auth/email/verify", json=body, headers=SAME_ORIGIN)

    assert refused.status_code == 403
    assert holder_user_after == holder_user
    assert confirmed_by_requester.status_code == 200, "the refusal consumed nothing"
    assert (await signed_in_user(browser))["id"] == user["id"]


@pytest.mark.asyncio
async def test_email_change_is_confirmed_by_code_too(browser, app):
    user = await sign_in(browser, app, "old@example.com")

    _, code = await request_email_change(browser, app, "New@Example.com")
    confirmed = await browser.post(
        "/v1/auth/email/verify", json={"email": "new@example.com", "code": code}, headers=SAME_ORIGIN
    )

    assert confirmed.status_code == 200, confirmed.text
    assert (await signed_in_user(browser))["id"] == user["id"]
    assert (await signed_in_user(browser))["email"] == "new@example.com"


@pytest.mark.asyncio
async def test_email_change_to_an_address_another_account_holds_is_refused(browser, app, session):
    session.add(UserAccount(id="other", email="taken@example.com"))
    await session.commit()
    await sign_in(browser, app, "me@example.com")

    response = await browser.post("/v1/auth/email/change", json={"email": "taken@example.com"}, headers=SAME_ORIGIN)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_email_change_link_fails_if_another_account_took_the_address_meanwhile(browser, app, session):
    await sign_in(browser, app, "me@example.com")
    token, _ = await request_email_change(browser, app, "new@example.com")
    session.add(UserAccount(id="other", email="new@example.com"))
    await session.commit()

    response = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    assert response.status_code == 400
    assert (await signed_in_user(browser))["email"] == "me@example.com"


# A failed auth email fails the request and is logged


class FailingMailer:
    async def send(self, email: Email) -> None:
        raise MailDeliveryError("SMTP delivery failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/v1/auth/email/start", "/v1/auth/email/change"])
async def test_failed_auth_email_fails_the_request_and_logs_an_error(browser, app, session, endpoint):
    await sign_in(browser, app, "me@example.com")
    await session.exec(delete(EmailChallenge))
    await session.commit()
    app.state.mailer = FailingMailer()
    errors: list[str] = []
    sink = logger.add(lambda message: errors.append(message), level="ERROR")
    try:
        response = await browser.post(endpoint, json={"email": "reader@example.com"}, headers=SAME_ORIGIN)
    finally:
        logger.remove(sink)

    assert response.status_code == 502
    assert any("Auth email to an address at example.com failed" in error for error in errors)
    assert (await session.exec(select(EmailChallenge))).all() == []


@pytest.mark.asyncio
async def test_smtp_mailer_reports_an_unreachable_server_as_a_delivery_error():
    mailer = SmtpMailer(host="127.0.0.1", port=1, username="", password="", sender="yapit@example.com")

    with pytest.raises(MailDeliveryError):
        await mailer.send(Email(to="reader@example.com", subject="s", text="t", html="h"))


# With auth disabled every request is the selfhost user and no auth table is read


@pytest.mark.asyncio
async def test_auth_disabled_makes_every_request_the_selfhost_user_without_reading_auth_tables(app, real_auth):
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        with settings_changed(app, auth_enabled=False, github_client_id="github-client"):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=APP_URL,
                headers={"Authorization": "Bearer yapit_nope"},
                cookies={SESSION_COOKIE: "stale"},
            ) as client:
                session_state = await client.get("/v1/auth/session")
                preferences = await client.patch("/v1/users/me/preferences", json={"pinned_voices": ["a"]})
                sign_in_endpoints = [
                    await client.get("/v1/auth/oauth/github/start"),
                    await client.post("/v1/auth/email/start", json={"email": "a@example.com"}),
                    await client.post("/v1/auth/email/change", json={"email": "a@example.com"}),
                    await client.get("/v1/auth/tokens"),
                    await client.post("/v1/auth/tokens", json={"label": "x"}),
                    await client.delete("/v1/auth/identities/github"),
                    await client.patch("/v1/users/me", json={"name": "x"}),
                ]
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert session_state.json() == {"auth_enabled": False, "providers": [], "user": None}
    assert preferences.status_code == 200
    assert [r.status_code for r in sign_in_endpoints] == [404] * len(sign_in_endpoints)
    assert statements, "the preferences write should have reached the database"
    auth_tables = ("useraccount", "authsession", "emailchallenge", "oauthidentity")
    assert not [s for s in statements if any(table in s for table in auth_tables)]


# Account deletion and anonymous documents


@pytest.mark.asyncio
async def test_account_deletion_deletes_the_account_and_its_sessions(browser, app, session):
    user = await sign_in(browser, app, "reader@example.com")

    response = await browser.delete("/v1/users/me", headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert await session.get(UserAccount, user["id"]) is None
    assert (await session.exec(select(EmailChallenge))).all() == []
    assert await signed_in_user(browser) is None
    assert (await sign_in(browser, app, "reader@example.com"))["id"] != user["id"]


@pytest.mark.asyncio
async def test_documents_made_anonymously_are_claimed_on_sign_in(browser, app, _test_settings, session):
    anonymous_id = "4f1c-guest"
    anonymous_token = sign_anonymous_id(anonymous_id, _test_settings.anonymous_session_secret)
    created = await browser.post(
        "/v1/documents/text",
        json={"content": "Written before signing up."},
        headers={"X-Anonymous-ID": anonymous_id, "X-Anonymous-Token": anonymous_token},
    )
    assert created.status_code == 201, created.text

    user = await sign_in(browser, app, "reader@example.com")
    claimed = await browser.post(
        "/v1/users/claim-anonymous",
        json={"anonymous_token": anonymous_token},
        headers={**SAME_ORIGIN, "X-Anonymous-ID": anonymous_id},
    )

    assert claimed.json() == {"claimed_documents": 1}
    document = await session.get(Document, created.json()["id"])
    assert document is not None and document.user_id == user["id"]


# The WebSocket handshake


def websocket(headers: dict[str, str]) -> WebSocket:
    async def never(*_):
        raise AssertionError("the handshake check should not touch the socket")

    scope = {
        "type": "websocket",
        "path": "/v1/ws/tts",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return WebSocket(scope, receive=never, send=never)


@pytest.mark.asyncio
async def test_websocket_accepts_the_session_cookie_from_the_app_origin(browser, app, _test_settings):
    user = await sign_in(browser, app, "reader@example.com")
    cookie = browser.cookies[SESSION_COOKIE]

    ws_user = await authenticate_ws(websocket({"Cookie": f"{SESSION_COOKIE}={cookie}", **SAME_ORIGIN}), _test_settings)

    assert ws_user.id == user["id"]


@pytest.mark.asyncio
async def test_websocket_with_the_session_cookie_from_another_origin_is_refused(browser, app, _test_settings):
    await sign_in(browser, app, "reader@example.com")
    cookie = browser.cookies[SESSION_COOKIE]

    with pytest.raises(WebSocketException):
        await authenticate_ws(
            websocket({"Cookie": f"{SESSION_COOKIE}={cookie}", "Origin": "https://evil.example"}), _test_settings
        )


@pytest.mark.asyncio
async def test_websocket_accepts_an_api_token(api_token, _test_settings):
    token = api_token
    ws_user = await authenticate_ws(websocket({"Authorization": f"Bearer {token}"}), _test_settings)

    assert ws_user.id == "cli-user"


@pytest.mark.asyncio
async def test_websocket_with_auth_disabled_is_the_selfhost_user(_test_settings):
    settings = _test_settings.model_copy(update={"auth_enabled": False})

    assert await authenticate_ws(websocket({}), settings) == SELFHOST_USER
