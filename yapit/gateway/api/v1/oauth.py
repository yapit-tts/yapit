from typing import Annotated
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from loguru import logger

from yapit.gateway.auth import Credentials, request_credentials, require_auth_enabled, signed_in_user_id
from yapit.gateway.auth.oauth import (
    OAUTH_STATE_COOKIE,
    PROVIDERS,
    STATE_LIFETIME,
    OAuthError,
    OAuthFailed,
    OAuthMode,
    PendingOAuth,
    Provider,
    begin,
    enabled_providers,
    fetch_profile,
    is_same_origin_path,
    provider_http,
    resolve_account,
    take_pending,
)
from yapit.gateway.auth.sessions import (
    app_origin,
    clear_auth_cookie,
    create_browser_session,
    revoke_session,
    session_cookie_name,
    set_auth_cookie,
    set_session_cookie,
)
from yapit.gateway.config import Settings
from yapit.gateway.deps import DbSession, RedisClient, SettingsDep
from yapit.gateway.rate_limit import limiter

router = APIRouter(prefix="/v1/auth/oauth", tags=["Auth"])

SIGN_IN_PAGE = "/auth/sign-in"


def enabled_provider(provider: str, settings: SettingsDep) -> Provider:
    require_auth_enabled(settings)
    if provider not in enabled_providers(settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sign-in with {provider} is not enabled.")
    return PROVIDERS[provider]


EnabledProvider = Annotated[Provider, Depends(enabled_provider)]


@router.get("/{provider}/start")
@limiter.limit("30/hour")
async def start_oauth(
    request: Request,
    provider: EnabledProvider,
    settings: SettingsDep,
    db: DbSession,
    redis: RedisClient,
    credentials: Annotated[Credentials, Depends(request_credentials)],
    return_to: str = "/",
    mode: OAuthMode = OAuthMode.sign_in,
) -> RedirectResponse:
    """Send the browser to the provider. In link mode the identity attaches to the signed-in user."""
    if not is_same_origin_path(return_to):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="return_to must be a path on this site.")
    user_id = None
    if mode == OAuthMode.link:
        user_id = await signed_in_user_id(db, settings, credentials)
        if user_id is None:
            return _redirect(settings, SIGN_IN_PAGE, OAuthError.not_signed_in)
    authorize_url, state = await begin(redis, settings, provider, mode, return_to, user_id)
    response = RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, OAUTH_STATE_COOKIE, state, int(STATE_LIFETIME.total_seconds()), settings)
    return response


@router.get("/{provider}/callback")
async def oauth_callback(
    request: Request,
    provider: EnabledProvider,
    settings: SettingsDep,
    db: DbSession,
    redis: RedisClient,
    http: Annotated[httpx.AsyncClient, Depends(provider_http)],
    credentials: Annotated[Credentials, Depends(request_credentials)],
) -> RedirectResponse:
    """Where the provider sends the browser back: sign in (or link) and go on to `return_to`, or to an error."""
    params = dict(request.query_params)
    try:
        pending = await take_pending(redis, provider, params.get("state"), request.cookies.get(OAUTH_STATE_COOKIE))
        profile = await fetch_profile(http, settings, provider, pending, params)
        current_user_id = await signed_in_user_id(db, settings, credentials)
        account = await resolve_account(db, provider, profile, pending, current_user_id)
    except OAuthFailed as failed:
        logger.info(f"OAuth with {provider.name} refused: {failed.error}")
        response = _redirect(settings, _error_page(failed.pending), failed.error)
        clear_auth_cookie(response, OAUTH_STATE_COOKIE, settings)
        return response

    response = _redirect(settings, pending.return_to)
    clear_auth_cookie(response, OAUTH_STATE_COOKIE, settings)
    if pending.mode == OAuthMode.sign_in:
        if previous := request.cookies.get(session_cookie_name(settings)):
            await revoke_session(db, previous)
        token, expires = create_browser_session(db, account.id)
        await db.commit()
        set_session_cookie(response, token, expires, settings)
        logger.info(f"User {account.id} signed in with {provider.name}")
    else:
        logger.info(f"User {account.id} connected {provider.name}")
    return response


def _error_page(pending: PendingOAuth | None) -> str:
    """Link mode reports on the page it started from, where the person is still signed in; sign-in on the sign-in page."""
    if pending is not None and pending.mode == OAuthMode.link:
        return pending.return_to
    return SIGN_IN_PAGE


def _redirect(settings: Settings, path: str, error: OAuthError | None = None) -> RedirectResponse:
    if error is not None:
        url = urlsplit(path)
        query = "&".join(filter(None, [url.query, urlencode({"error": error.value})]))
        path = urlunsplit(("", "", url.path, query, url.fragment))
    return RedirectResponse(f"{app_origin(settings)}{path}", status_code=status.HTTP_302_FOUND)
