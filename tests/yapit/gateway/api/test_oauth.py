"""Google and GitHub sign-in through the gateway's API, against a stub provider."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlmodel import select

from tests.yapit.gateway.api.conftest import (
    APP_URL,
    SAME_ORIGIN,
    SESSION_COOKIE,
    settings_changed,
    sign_in,
    signed_in_user,
)
from yapit.gateway.auth.oauth import provider_http
from yapit.gateway.domain_models import OAuthIdentity, UserAccount

ISSUERS = {"google": "https://accounts.google.com", "github": "https://github.com/login/oauth"}
CLIENTS = {"google": ("google-client", "google-secret"), "github": ("github-client", "github-secret")}


@dataclass
class ProviderAccount:
    """Who signs in at the provider, as the provider describes them."""

    id: str
    email: str | None
    verified: bool = True
    name: str = "Ada Reader"


@dataclass
class StubProvider:
    """Google's and GitHub's authorize, token and profile endpoints, holding PKCE and the client secret to account."""

    account: ProviderAccount = field(default_factory=lambda: ProviderAccount(id="4242", email="reader@example.com"))
    grants: dict[str, dict] = field(default_factory=dict)

    def authorize(self, authorize_url: str) -> dict[str, str]:
        """Consent at the provider: the query the provider redirects back to the callback with."""
        url = urlsplit(authorize_url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        provider = "google" if url.netloc == "accounts.google.com" else "github"
        assert query["client_id"] == CLIENTS[provider][0]
        assert query["redirect_uri"] == f"{APP_URL}/api/v1/auth/oauth/{provider}/callback"
        assert query["code_challenge_method"] == "S256"
        code = secrets.token_urlsafe(8)
        self.grants[code] = {"provider": provider, **query}
        return {"code": code, "state": query["state"], "iss": ISSUERS[provider]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if (request.url.host, request.url.path) in (
            ("oauth2.googleapis.com", "/token"),
            ("github.com", "/login/oauth/access_token"),
        ):
            return self._token(request)
        if request.headers.get("authorization") != "Bearer access-token":
            return httpx.Response(401)
        a = self.account
        match request.url.host, request.url.path:
            case "openidconnect.googleapis.com", "/v1/userinfo":
                return httpx.Response(
                    200, json={"sub": a.id, "email": a.email, "email_verified": a.verified, "name": a.name}
                )
            case "api.github.com", "/user":
                return httpx.Response(200, json={"id": int(a.id), "login": "ada", "name": a.name})
            case "api.github.com", "/user/emails":
                emails = [{"email": "ada@users.noreply.github.com", "primary": False, "verified": True}]
                if a.email:
                    emails.append({"email": a.email, "primary": True, "verified": a.verified})
                return httpx.Response(200, json=emails)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        grant = self.grants.pop(form["code"], None)
        verifier_hash = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
        if (
            grant is None
            or verifier_hash.rstrip(b"=").decode() != grant["code_challenge"]
            or form["redirect_uri"] != grant["redirect_uri"]
            or (form["client_id"], form["client_secret"]) != CLIENTS[grant["provider"]]
        ):
            return httpx.Response(200, json={"error": "bad_verification_code"})
        return httpx.Response(200, json={"access_token": "access-token", "token_type": "bearer"})


@pytest.fixture
def provider(app):
    stub = StubProvider()

    async def stub_http():
        async with httpx.AsyncClient(transport=httpx.MockTransport(stub.handle)) as client:
            yield client

    app.dependency_overrides[provider_http] = stub_http
    with settings_changed(
        app,
        google_client_id=CLIENTS["google"][0],
        google_client_secret=CLIENTS["google"][1],
        github_client_id=CLIENTS["github"][0],
        github_client_secret=CLIENTS["github"][1],
    ):
        yield stub
    del app.dependency_overrides[provider_http]


async def start(browser, provider_name: str, **params) -> httpx.Response:
    response = await browser.get(f"/v1/auth/oauth/{provider_name}/start", params=params)
    assert response.status_code == 302, response.text
    return response


async def callback(browser, provider_name: str, query: dict[str, str]) -> str:
    """The callback's redirect, as a path on the app."""
    response = await browser.get(f"/v1/auth/oauth/{provider_name}/callback", params=query)
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(APP_URL + "/")
    return location.removeprefix(APP_URL)


async def oauth_sign_in(browser, provider: StubProvider, provider_name: str = "github", **params) -> str:
    """Go through the whole flow in this browser; return where it ends up."""
    started = await start(browser, provider_name, **params)
    return await callback(browser, provider_name, provider.authorize(started.headers["location"]))


async def identities(session) -> list[tuple[str, str, str]]:
    rows = (await session.exec(select(OAuthIdentity))).all()
    return sorted((row.provider, row.provider_account_id, row.user_id) for row in rows)


# Which account an identity signs in to


@pytest.mark.asyncio
async def test_known_identity_signs_its_user_in_whatever_email_the_provider_now_gives(browser, provider, session):
    session.add(UserAccount(id="stack-auth-id", email="old@example.com"))
    await session.flush()
    session.add(OAuthIdentity(provider="github", provider_account_id="4242", user_id="stack-auth-id"))
    await session.commit()
    provider.account = ProviderAccount(id="4242", email="new@example.com", verified=False)

    landed = await oauth_sign_in(browser, provider, return_to="/listen/abc")

    assert landed == "/listen/abc"
    user = await signed_in_user(browser)
    assert user["id"] == "stack-auth-id"
    assert user["identities"] == [{"provider": "github", "email": "new@example.com"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["google", "github"])
async def test_verified_email_links_the_identity_to_the_account_holding_it(browser, provider, session, provider_name):
    session.add(UserAccount(id="email-user", email="reader@example.com"))
    await session.commit()
    provider.account = ProviderAccount(id="77", email="Reader@Example.com", verified=True)

    landed = await oauth_sign_in(browser, provider, provider_name)

    assert landed == "/"
    user = await signed_in_user(browser)
    assert user["id"] == "email-user"
    assert user["identities"] == [{"provider": provider_name, "email": "reader@example.com"}]
    assert await identities(session) == [(provider_name, "77", "email-user")]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["google", "github"])
async def test_unverified_email_signs_in_to_nothing(browser, provider, session, provider_name):
    session.add(UserAccount(id="email-user", email="reader@example.com"))
    await session.commit()
    provider.account = ProviderAccount(id="77", email="reader@example.com", verified=False)

    landed = await oauth_sign_in(browser, provider, provider_name)

    assert landed == "/auth/sign-in?error=email_unverified"
    assert await signed_in_user(browser) is None
    assert await identities(session) == []
    assert [a.id for a in (await session.exec(select(UserAccount))).all()] == ["email-user"]


@pytest.mark.asyncio
async def test_github_account_without_an_email_signs_in_to_nothing(browser, provider, session):
    provider.account = ProviderAccount(id="77", email=None)

    landed = await oauth_sign_in(browser, provider)

    assert landed == "/auth/sign-in?error=email_unverified"
    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_new_verified_email_creates_an_account_named_after_the_provider_profile(browser, provider, session):
    provider.account = ProviderAccount(id="77", email="new@example.com", name="Ada Lovelace")

    await oauth_sign_in(browser, provider, "google")

    user = await signed_in_user(browser)
    assert (user["email"], user["name"]) == ("new@example.com", "Ada Lovelace")
    assert await identities(session) == [("google", "77", user["id"])]


@pytest.mark.asyncio
async def test_oauth_sign_in_sets_the_session_cookie_and_revokes_the_browsers_previous_session(
    browser, app, provider, session
):
    await sign_in(browser, app, "other@example.com")
    previous = browser.cookies[SESSION_COOKIE]

    await oauth_sign_in(browser, provider)

    assert browser.cookies[SESSION_COOKIE] != previous
    assert (await signed_in_user(browser))["email"] == "reader@example.com"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=APP_URL, cookies={SESSION_COOKIE: previous}
    ) as replay:
        assert await signed_in_user(replay) is None


# The callback's iss (RFC 9207) and state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("iss", "signed_in"),
    [("https://github.com/login/oauth", True), ("https://github.com", False), (None, True)],
    ids=["correct", "wrong", "absent"],
)
async def test_callback_iss_must_be_the_providers_when_present(browser, provider, iss, signed_in):
    started = await start(browser, "github")
    query = provider.authorize(started.headers["location"])
    if iss is None:
        del query["iss"]
    else:
        query["iss"] = iss

    landed = await callback(browser, "github", query)

    assert landed == ("/" if signed_in else "/auth/sign-in?error=issuer")
    assert (await signed_in_user(browser) is not None) == signed_in


@pytest.mark.asyncio
async def test_callback_in_a_browser_that_did_not_start_the_flow_is_refused(browser, app, provider):
    """Login CSRF: someone else's callback URL, opened in the victim's browser, signs it in to nothing."""
    started = await start(browser, "github")
    query = provider.authorize(started.headers["location"])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=APP_URL) as victim:
        landed = await callback(victim, "github", query)
        assert landed == "/auth/sign-in?error=state"
        assert await signed_in_user(victim) is None


@pytest.mark.asyncio
async def test_callback_at_another_providers_endpoint_is_refused(browser, provider):
    started = await start(browser, "github")

    landed = await callback(browser, "google", provider.authorize(started.headers["location"]))

    assert landed == "/auth/sign-in?error=state"


@pytest.mark.asyncio
async def test_callback_whose_state_is_not_the_browsers_is_refused(browser, provider):
    first = await start(browser, "github")
    first_query = provider.authorize(first.headers["location"])
    await start(browser, "github")  # the browser's state cookie now names the second flow

    landed = await callback(browser, "github", first_query)

    assert landed == "/auth/sign-in?error=state"
    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_callback_works_once(browser, provider):
    started = await start(browser, "github")
    query = provider.authorize(started.headers["location"])
    state_cookie = browser.cookies["yapit_oauth_state"]
    await callback(browser, "github", query)
    await browser.post("/v1/auth/sign-out", headers=SAME_ORIGIN)
    browser.cookies.set("yapit_oauth_state", state_cookie)

    landed = await callback(browser, "github", query)

    assert landed == "/auth/sign-in?error=state"
    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_cancelling_at_the_provider_lands_on_the_sign_in_page(browser, provider):
    started = await start(browser, "github")
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]

    landed = await callback(browser, "github", {"error": "access_denied", "state": state})

    assert landed == "/auth/sign-in?error=denied"


@pytest.mark.asyncio
async def test_code_the_provider_refuses_lands_on_the_sign_in_page(browser, provider):
    started = await start(browser, "github")
    query = provider.authorize(started.headers["location"])
    provider.grants.clear()

    landed = await callback(browser, "github", query)

    assert landed == "/auth/sign-in?error=provider"
    assert await signed_in_user(browser) is None


@pytest.mark.asyncio
async def test_start_refuses_a_return_to_off_the_site(browser, provider):
    for return_to in ("https://evil.example/", "//evil.example/", "/\\evil.example"):
        response = await browser.get("/v1/auth/oauth/github/start", params={"return_to": return_to})
        assert response.status_code == 400, return_to


# Link mode, from account settings


@pytest.mark.asyncio
async def test_link_mode_connects_the_identity_to_the_signed_in_user(browser, app, provider, session):
    user = await sign_in(browser, app, "me@example.com")
    session_cookie = browser.cookies[SESSION_COOKIE]
    provider.account = ProviderAccount(id="77", email="someone-else@example.com", verified=False)

    landed = await oauth_sign_in(browser, provider, mode="link", return_to="/account/settings")

    assert landed == "/account/settings"
    assert browser.cookies[SESSION_COOKIE] == session_cookie
    assert (await signed_in_user(browser))["identities"] == [
        {"provider": "github", "email": "someone-else@example.com"}
    ]
    assert await identities(session) == [("github", "77", user["id"])]


@pytest.mark.asyncio
async def test_link_mode_refuses_an_identity_that_belongs_to_another_user(browser, app, provider, session):
    session.add(UserAccount(id="owner", email="owner@example.com"))
    await session.flush()
    session.add(OAuthIdentity(provider="github", provider_account_id="4242", user_id="owner"))
    await session.commit()
    await sign_in(browser, app, "me@example.com")

    landed = await oauth_sign_in(browser, provider, mode="link", return_to="/account/settings")

    assert landed == "/account/settings?error=identity_taken"
    assert (await signed_in_user(browser))["identities"] == []
    assert await identities(session) == [("github", "4242", "owner")]


@pytest.mark.asyncio
async def test_link_mode_needs_a_signed_in_user(browser, provider):
    response = await browser.get("/v1/auth/oauth/github/start", params={"mode": "link"})

    assert response.status_code == 302
    assert response.headers["location"] == f"{APP_URL}/auth/sign-in?error=not_signed_in"


@pytest.mark.asyncio
async def test_link_mode_refuses_when_the_user_signed_out_in_between(browser, app, provider, session):
    await sign_in(browser, app, "me@example.com")
    started = await start(browser, "github", mode="link", return_to="/account/settings")
    await browser.post("/v1/auth/sign-out", headers=SAME_ORIGIN)

    landed = await callback(browser, "github", provider.authorize(started.headers["location"]))

    assert landed == "/account/settings?error=not_signed_in"
    assert await identities(session) == []


@pytest.mark.asyncio
async def test_link_mode_refuses_when_another_user_signed_in_in_between(browser, app, provider, session):
    await sign_in(browser, app, "starter@example.com")
    started = await start(browser, "github", mode="link", return_to="/account/settings")
    await sign_in(browser, app, "someone-else@example.com")

    landed = await callback(browser, "github", provider.authorize(started.headers["location"]))

    assert landed == "/account/settings?error=not_signed_in"
    assert await identities(session) == []


@pytest.mark.asyncio
async def test_disconnecting_a_provider_removes_only_the_users_own_identity(browser, app, provider, session):
    session.add(UserAccount(id="other", email="other@example.com"))
    await session.flush()
    session.add(OAuthIdentity(provider="github", provider_account_id="999", user_id="other"))
    await session.commit()
    await sign_in(browser, app, "me@example.com")
    await oauth_sign_in(browser, provider, mode="link", return_to="/account/settings")

    first = await browser.delete("/v1/auth/identities/github", headers=SAME_ORIGIN)
    second = await browser.delete("/v1/auth/identities/github", headers=SAME_ORIGIN)

    assert (first.status_code, second.status_code) == (204, 404)
    assert await identities(session) == [("github", "999", "other")]
    assert (await signed_in_user(browser))["email"] == "me@example.com"


# A provider without a client id


@pytest.mark.asyncio
async def test_provider_without_a_client_id_is_hidden_and_refused(browser, app, provider):
    with settings_changed(app, github_client_id=""):
        session_state = (await browser.get("/v1/auth/session")).json()
        response = await browser.get("/v1/auth/oauth/github/start")

    assert session_state["providers"] == ["google"]
    assert response.status_code == 404
