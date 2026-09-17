"""Read-only Gmail / Sheets / Outlook OAuth — connect, reject writes, persist tokens."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import get_settings
from app.core.privacy import decrypt_secret
from app.integrations.readonly import WriteAttemptError
from app.integrations.source_oauth import (
    TokenBundle,
    assert_readonly_grant,
    authorization_url,
    requested_scopes,
)
from app.models.vault import SourceConnection
from app.services import oauth_state


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)


@pytest.fixture
def fake_oauth_redis():
    redis = _FakeRedis()
    with patch.object(oauth_state, "get_redis", AsyncMock(return_value=redis)):
        yield redis


@pytest.fixture
def google_oauth_clients(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("google-secret"))
    return settings


@pytest.fixture
def microsoft_oauth_clients(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "microsoft_client_id", "ms-client")
    monkeypatch.setattr(settings, "microsoft_client_secret", SecretStr("ms-secret"))
    return settings


def test_gmail_url_is_readonly_only(google_oauth_clients):
    url = authorization_url("gmail", "state-token")
    params = parse_qs(urlparse(url).query)
    scopes = params["scope"][0]
    assert "gmail.readonly" in scopes
    assert "gmail.modify" not in scopes
    assert "gmail.send" not in scopes
    assert params["include_granted_scopes"] == ["false"]
    assert params["access_type"] == ["offline"]
    assert "/sources/callback" in params["redirect_uri"][0]


def test_outlook_url_is_mail_read_only(microsoft_oauth_clients):
    url = authorization_url("outlook", "state-token")
    params = parse_qs(urlparse(url).query)
    scopes = params["scope"][0]
    assert "Mail.Read" in scopes
    assert "Mail.Send" not in scopes
    assert "Mail.ReadWrite" not in scopes
    assert "offline_access" in scopes


def test_grant_rejects_gmail_write_scopes():
    with pytest.raises(WriteAttemptError):
        assert_readonly_grant(
            "gmail",
            "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.modify",
        )


def test_grant_rejects_sheets_write_scope():
    with pytest.raises(WriteAttemptError):
        assert_readonly_grant("sheets", "https://www.googleapis.com/auth/spreadsheets")


def test_grant_accepts_microsoft_short_mail_read():
    granted = assert_readonly_grant("outlook", "Mail.Read offline_access")
    assert "https://graph.microsoft.com/Mail.Read" in granted.split()


def test_sheets_requested_scope_is_readonly():
    assert requested_scopes("sheets") == (
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    )
    assert "spreadsheets.readonly" in " ".join(requested_scopes("sheets"))
    assert "spreadsheets" != requested_scopes("sheets")[0]


@pytest.mark.asyncio
async def test_list_sources_not_configured_without_clients(
    client: AsyncClient, auth_headers
):
    response = await client.get("/api/sources", headers=auth_headers)
    assert response.status_code == 200
    by_provider = {row["provider"]: row for row in response.json()}
    assert by_provider["gmail"]["status"] == "not_configured"
    assert by_provider["sheets"]["status"] == "not_configured"
    assert by_provider["outlook"]["status"] == "not_configured"


@pytest.mark.asyncio
async def test_list_sources_awaiting_consent_when_client_set(
    client: AsyncClient, auth_headers, google_oauth_clients
):
    response = await client.get("/api/sources", headers=auth_headers)
    assert response.status_code == 200
    by_provider = {row["provider"]: row for row in response.json()}
    assert by_provider["gmail"]["status"] == "awaiting_consent"
    assert by_provider["sheets"]["status"] == "awaiting_consent"
    assert by_provider["outlook"]["status"] == "not_configured"


@pytest.mark.asyncio
async def test_connect_without_clients_is_conflict(client: AsyncClient, auth_headers):
    response = await client.post("/api/sources/gmail/connect", headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Client id is not set"


@pytest.mark.asyncio
async def test_connect_unknown_provider_is_not_found(client: AsyncClient, auth_headers):
    response = await client.post("/api/sources/imap/connect", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_connect_returns_readonly_authorization_url(
    client: AsyncClient, auth_headers, google_oauth_clients, fake_oauth_redis
):
    response = await client.post("/api/sources/gmail/connect", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "gmail.readonly" in body["scopes"]
    assert "gmail.modify" not in body["authorization_url"]
    assert body["redirect_uri"].endswith("/sources/callback")
    params = parse_qs(urlparse(body["authorization_url"]).query)
    assert fake_oauth_redis.store
    assert f"oauth_state:{params['state'][0]}" in fake_oauth_redis.store


@pytest.mark.asyncio
async def test_callback_stores_encrypted_refresh_token(
    client: AsyncClient,
    auth_headers,
    session: AsyncSession,
    google_oauth_clients,
    fake_oauth_redis,
):
    start = await client.post("/api/sources/gmail/connect", headers=auth_headers)
    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    bundle = TokenBundle(
        refresh_token="refresh-gmail-secret",
        access_token="access-gmail",
        expires_at=datetime.now(timezone.utc),
        granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        external_account_id="owner@example.com",
        display_name="owner@example.com",
    )
    with patch(
        "app.integrations.source_oauth.exchange_authorization_code",
        AsyncMock(return_value=bundle),
    ):
        response = await client.post(
            "/api/sources/callback",
            headers=auth_headers,
            json={"code": "auth-code", "state": state},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "connected"
    assert body["provider"] == "gmail"
    assert "gmail.readonly" in (body["granted_scopes"] or "")
    stored = (
        await session.execute(select(SourceConnection).where(SourceConnection.provider == "gmail"))
    ).scalar_one()
    assert stored.encrypted_refresh_token
    assert "refresh-gmail-secret" not in stored.encrypted_refresh_token
    assert decrypt_secret(stored.encrypted_refresh_token) == "refresh-gmail-secret"


@pytest.mark.asyncio
async def test_callback_rejects_write_grant(
    client: AsyncClient, auth_headers, google_oauth_clients, fake_oauth_redis
):
    start = await client.post("/api/sources/gmail/connect", headers=auth_headers)
    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    with patch(
        "app.integrations.source_oauth.exchange_authorization_code",
        AsyncMock(
            side_effect=WriteAttemptError(
                "gmail consent included disallowed scopes: "
                "https://www.googleapis.com/auth/gmail.modify"
            )
        ),
    ):
        response = await client.post(
            "/api/sources/callback",
            headers=auth_headers,
            json={"code": "auth-code", "state": state},
        )
    assert response.status_code == 400
    assert "gmail.modify" in response.json()["detail"]


@pytest.mark.asyncio
async def test_callback_rejects_forged_state(
    client: AsyncClient, auth_headers, fake_oauth_redis
):
    response = await client.post(
        "/api/sources/callback",
        headers=auth_headers,
        json={"code": "auth-code", "state": "forged"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_disconnect_wipes_refresh_token(
    client: AsyncClient,
    auth_headers,
    session: AsyncSession,
    google_oauth_clients,
    fake_oauth_redis,
):
    start = await client.post("/api/sources/gmail/connect", headers=auth_headers)
    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    bundle = TokenBundle(
        refresh_token="refresh-gmail-secret",
        access_token="access-gmail",
        expires_at=datetime.now(timezone.utc),
        granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        external_account_id="owner@example.com",
        display_name="owner@example.com",
    )
    with patch(
        "app.integrations.source_oauth.exchange_authorization_code",
        AsyncMock(return_value=bundle),
    ):
        await client.post(
            "/api/sources/callback",
            headers=auth_headers,
            json={"code": "auth-code", "state": state},
        )
    response = await client.post("/api/sources/gmail/disconnect", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    stored = (
        await session.execute(select(SourceConnection).where(SourceConnection.provider == "gmail"))
    ).scalar_one()
    assert stored.encrypted_refresh_token is None
