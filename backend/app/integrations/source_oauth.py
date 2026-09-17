"""Read-only OAuth for Gmail, Google Sheets and Outlook.

Write scopes are rejected even if the identity provider tries to grant them.
Tokens are never logged. The SPA completes the code exchange at
`/sources/callback` so cookies stay first-party.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.privacy import sanitize_error
from app.integrations.readonly import READ_ONLY_SCOPES, WriteAttemptError, assert_readonly

PROVIDERS = ("gmail", "sheets", "outlook")

GOOGLE_AUTHORIZATION = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"
MICROSOFT_AUTHORIZATION = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_ME = "https://graph.microsoft.com/v1.0/me"

# Microsoft v2 always needs offline_access to mint a refresh token.
MICROSOFT_EXTRA_SCOPES = ("offline_access",)
# Google sometimes echoes openid/email/profile even when we did not ask.
HARMLESS_IDENTITY_SCOPES = frozenset(
    {
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "offline_access",
    }
)
SCOPE_ALIASES = {
    "Mail.Read": "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.Read": "https://graph.microsoft.com/Mail.Read",
}


@dataclass(frozen=True)
class TokenBundle:
    refresh_token: str
    access_token: str
    expires_at: datetime | None
    granted_scopes: str
    external_account_id: str
    display_name: str


def redirect_uri() -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/sources/callback"


def requested_scopes(provider: str) -> tuple[str, ...]:
    if provider not in READ_ONLY_SCOPES:
        raise ValueError(f"Unknown source provider: {provider}")
    if provider == "outlook":
        return MICROSOFT_EXTRA_SCOPES + READ_ONLY_SCOPES[provider]
    return READ_ONLY_SCOPES[provider]


def client_configured(provider: str) -> bool:
    settings = get_settings()
    if provider in ("gmail", "sheets"):
        return bool(settings.google_client_id and settings.google_client_secret.get_secret_value())
    if provider == "outlook":
        return bool(
            settings.microsoft_client_id and settings.microsoft_client_secret.get_secret_value()
        )
    return False


def authorization_url(provider: str, state: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown source provider: {provider}")
    if not client_configured(provider):
        raise LookupError("Client id is not set")
    settings = get_settings()
    scopes = " ".join(requested_scopes(provider))
    if provider == "outlook":
        params = {
            "client_id": settings.microsoft_client_id,
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "response_mode": "query",
            "scope": scopes,
            "state": state,
        }
        return f"{MICROSOFT_AUTHORIZATION}?{urlencode(params)}"
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    return f"{GOOGLE_AUTHORIZATION}?{urlencode(params)}"


def split_scopes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part for part in raw.replace(",", " ").split() if part]


def _canonical_scope(scope: str) -> str:
    return SCOPE_ALIASES.get(scope, scope)


def assert_readonly_grant(provider: str, granted: str | None) -> str:
    """Accept only the declared read-only scopes (plus harmless identity scopes)."""
    required = {_canonical_scope(scope) for scope in READ_ONLY_SCOPES[provider]}
    allowed = required | HARMLESS_IDENTITY_SCOPES
    scopes = [_canonical_scope(scope) for scope in split_scopes(granted)] or list(required)
    extras = [scope for scope in scopes if scope not in allowed]
    if extras:
        raise WriteAttemptError(
            f"{provider} consent included disallowed scopes: {' '.join(extras)}"
        )
    present = set(scopes)
    if granted and any(scope not in present for scope in required):
        raise ValueError(f"{provider} consent omitted required read-only scopes")
    assert_readonly(provider, "list")
    return " ".join(scopes)


def _expires_at(payload: dict[str, Any]) -> datetime | None:
    seconds = payload.get("expires_in")
    if seconds is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds))


async def _post_token(url: str, data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, data=data)
        response.raise_for_status()
        return response.json()


async def _google_identity(access_token: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
    account = payload.get("email") or payload.get("id")
    if not account:
        raise ValueError("Google did not return an account identity")
    return str(account), str(payload.get("email") or "Google")


async def _microsoft_identity(access_token: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            MICROSOFT_ME,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
    account = (
        payload.get("userPrincipalName")
        or payload.get("mail")
        or payload.get("id")
    )
    if not account:
        raise ValueError("Microsoft did not return an account identity")
    label = payload.get("displayName") or payload.get("mail") or "Outlook"
    return str(account), str(label)


async def exchange_authorization_code(provider: str, code: str) -> TokenBundle:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown source provider: {provider}")
    if not client_configured(provider):
        raise LookupError("Client id is not set")
    settings = get_settings()
    try:
        if provider == "outlook":
            payload = await _post_token(
                MICROSOFT_TOKEN,
                {
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": redirect_uri(),
                    "grant_type": "authorization_code",
                    "scope": " ".join(requested_scopes(provider)),
                },
            )
            identity = _microsoft_identity
        else:
            payload = await _post_token(
                GOOGLE_TOKEN,
                {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "code": code,
                    "redirect_uri": redirect_uri(),
                    "grant_type": "authorization_code",
                },
            )
            identity = _google_identity
    except httpx.HTTPError as exc:
        raise ValueError(sanitize_error(str(exc))) from exc

    refresh = payload.get("refresh_token")
    access = payload.get("access_token")
    if not refresh or not access:
        raise ValueError("Consent did not return a refresh token")
    granted = assert_readonly_grant(provider, payload.get("scope"))
    try:
        external_id, display_name = await identity(str(access))
    except httpx.HTTPError as exc:
        raise ValueError(sanitize_error(str(exc))) from exc
    return TokenBundle(
        refresh_token=str(refresh),
        access_token=str(access),
        expires_at=_expires_at(payload),
        granted_scopes=granted,
        external_account_id=external_id,
        display_name=display_name,
    )


async def refresh_access_token(provider: str, refresh_token: str) -> tuple[str, datetime | None]:
    """Mint a short-lived access token. Never logs the refresh token."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown source provider: {provider}")
    if not client_configured(provider):
        raise LookupError("Client id is not set")
    settings = get_settings()
    try:
        if provider == "outlook":
            payload = await _post_token(
                MICROSOFT_TOKEN,
                {
                    "client_id": settings.microsoft_client_id,
                    "client_secret": settings.microsoft_client_secret.get_secret_value(),
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": " ".join(requested_scopes(provider)),
                },
            )
        else:
            payload = await _post_token(
                GOOGLE_TOKEN,
                {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    except httpx.HTTPError as exc:
        raise ValueError(sanitize_error(str(exc))) from exc
    access = payload.get("access_token")
    if not access:
        raise ValueError("Token refresh did not return an access token")
    return str(access), _expires_at(payload)
