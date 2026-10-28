"""Email sign-in, browser sessions and API tokens, through the gateway's API."""

import datetime as dt
import hashlib
import hmac
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import WebSocketException
from loguru import logger
from sqlalchemy import event
from sqlmodel import select, update
from starlette.websockets import WebSocket

from tests.yapit.gateway.api.conftest import APP_URL
from yapit.gateway.auth import authenticate_ws
from yapit.gateway.auth.mailer import Email, MailDeliveryError
from yapit.gateway.auth.sessions import SESSION_COOKIE, create_api_token
from yapit.gateway.config import get_settings
from yapit.gateway.db import get_engine
from yapit.gateway.domain_models import AuthSession, Document, EmailChallenge, UserAccount

SAME_ORIGIN = {"Origin": APP_URL}
THIRTY_DAYS_S = 30 * 24 * 3600


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest_asyncio.fixture
async def browser(app, real_auth):
    """A client at the app's origin that keeps cookies, like the browser the frontend runs in."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as client:
        yield client


@contextmanager
def settings_changed(app, **changes):
    original = app.dependency_overrides[get_settings]
    changed = original().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: changed
    try:
        yield changed
    finally:
        app.dependency_overrides[get_settings] = original


async def request_sign_in(browser, app, email: str) -> tuple[str, str]:
    """Ask for a sign-in email; return the link's token and the code, read off the mail as a person would."""
    response = await browser.post("/v1/auth/email/start", json={"email": email})
    assert response.status_code == 202, response.text
    mail: Email = app.state.mailer.sent[-1]
    link = next(word for word in mail.text.split() if "/auth/email?" in word)
    token = parse_qs(urlsplit(link).query)["token"][0]
    code = re.search(r"\b\d{6}\b", mail.text)
    assert code is not None
    return token, code.group()


async def sign_in(browser, app, email: str) -> dict:
    token, _ = await request_sign_in(browser, app, email)
    response = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)
    assert response.status_code == 200, response.text
    return response.json()["user"]


async def signed_in_user(browser) -> dict | None:
    response = await browser.get("/v1/auth/session")
    assert response.status_code == 200
    return response.json()["user"]


# Signing in and out


@pytest.mark.asyncio
async def test_new_address_signs_up_by_link_and_stays_signed_in(browser, app):
    user = await sign_in(browser, app, "new@example.com")

    assert user["email"] == "new@example.com"
    assert await signed_in_user(browser) == user


@pytest.mark.asyncio
async def test_migrated_address_signs_in_by_code_to_its_existing_account(browser, app, session):
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
async def test_sign_out_revokes_the_session(browser, app, session):
    await sign_in(browser, app, "reader@example.com")
    cookie = browser.cookies[SESSION_COOKIE]

    response = await browser.post("/v1/auth/sign-out", headers=SAME_ORIGIN)

    assert response.status_code == 204
    assert await signed_in_user(browser) is None
    browser.cookies.set(SESSION_COOKIE, cookie)
    assert await signed_in_user(browser) is None
    assert (await session.exec(select(AuthSession))).all() == []


# P3: a link or code works once, within 15 minutes, and 5 wrong codes kill the challenge


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


# P4: "email me a sign-in link" answers the same whether or not the address has an account


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


# P2: secrets are stored only as SHA-256 hashes


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
async def test_api_token_is_stored_only_as_its_hash(session):
    session.add(UserAccount(id="cli-user", email="cli@example.com"))
    await session.flush()
    token = create_api_token(session, "cli-user", "laptop")
    await session.commit()

    stored = (await session.exec(select(AuthSession))).one()

    assert token.startswith("yapit_")
    assert stored.token_hash == sha256(token)
    assert token not in repr(stored.model_dump())


# The session cookie


@pytest.mark.asyncio
async def test_session_cookie_flags(browser, app):
    token, _ = await request_sign_in(browser, app, "reader@example.com")

    response = await browser.post("/v1/auth/email/verify", json={"token": token}, headers=SAME_ORIGIN)

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
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
    assert "Secure" not in response.headers["set-cookie"]


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


# P6: cookie-authenticated state changes only from the app's origin


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
async def test_api_token_authenticates_without_an_origin(app, real_auth, session):
    session.add(UserAccount(id="cli-user", email="cli@example.com"))
    await session.flush()
    token = create_api_token(session, "cli-user", "laptop")
    await session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": f"Bearer {token}"}
    ) as cli:
        changed = await cli.patch("/v1/users/me/preferences", json={"pinned_voices": ["a"]})
        whoami = await cli.get("/v1/auth/session")

    assert changed.status_code == 200
    assert whoami.json()["user"]["id"] == "cli-user"


@pytest.mark.asyncio
async def test_unknown_api_token_is_refused(app, real_auth):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://cli", headers={"Authorization": "Bearer yapit_nope"}
    ) as cli:
        response = await cli.get("/v1/users/me/preferences")

    assert response.status_code == 401


# P7: a failed auth email fails the request and is logged


class FailingMailer:
    async def send(self, email: Email) -> None:
        raise MailDeliveryError("SMTP delivery via smtp.test:587 failed: ConnectionRefusedError()")


@pytest.mark.asyncio
async def test_failed_sign_in_email_fails_the_request_and_logs_an_error(browser, app, session):
    app.state.mailer = FailingMailer()
    errors: list[str] = []
    sink = logger.add(lambda message: errors.append(message), level="ERROR")
    try:
        response = await browser.post("/v1/auth/email/start", json={"email": "reader@example.com"})
    finally:
        logger.remove(sink)

    assert response.status_code == 502
    assert any("ConnectionRefusedError" in error for error in errors)
    assert (await session.exec(select(EmailChallenge))).all() == []


# P8: with auth disabled every request is the selfhost user and no auth table is read


@pytest.mark.asyncio
async def test_auth_disabled_makes_every_request_the_selfhost_user_without_reading_auth_tables(app, real_auth):
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        with settings_changed(app, auth_enabled=False):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=APP_URL,
                headers={"Authorization": "Bearer yapit_nope"},
                cookies={SESSION_COOKIE: "stale"},
            ) as client:
                session_state = await client.get("/v1/auth/session")
                preferences = await client.patch("/v1/users/me/preferences", json={"pinned_voices": ["a"]})
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert session_state.json() == {"auth_enabled": False, "user": None}
    assert preferences.status_code == 200
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
    assert (await session.exec(select(AuthSession))).all() == []
    assert await signed_in_user(browser) is None
    assert (await sign_in(browser, app, "reader@example.com"))["id"] != user["id"]


@pytest.mark.asyncio
async def test_documents_made_anonymously_are_claimed_on_sign_in(browser, app, _test_settings, session):
    anonymous_id = "4f1c-guest"
    anonymous_token = hmac.new(
        _test_settings.anonymous_session_secret.encode(), anonymous_id.encode(), hashlib.sha256
    ).hexdigest()
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
async def test_websocket_accepts_an_api_token(session, _test_settings):
    session.add(UserAccount(id="cli-user", email="cli@example.com"))
    await session.flush()
    token = create_api_token(session, "cli-user", "laptop")
    await session.commit()

    ws_user = await authenticate_ws(websocket({"Authorization": f"Bearer {token}"}), _test_settings)

    assert ws_user.id == "cli-user"
