"""Read-only source sync: attachments become unselected vault documents."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.privacy import encrypt_secret
from app.integrations.readonly import SyncPage, WriteAttemptError, assert_readonly
from app.integrations.source_fetch import fetch_gmail_messages
from app.models.vault import SourceConnection


@pytest.fixture
def vault_dir(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path))
    import app.providers as providers

    providers._storage_provider = None
    yield tmp_path
    providers._storage_provider = None


@pytest.fixture
def google_oauth_clients(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("google-secret"))
    return settings


async def _connected_gmail(session: AsyncSession, test_user, test_workspace) -> SourceConnection:
    source = SourceConnection(
        user_id=test_user.id,
        workspace_id=test_workspace.id,
        provider="gmail",
        display_name="Gmail",
        status="connected",
        granted_scopes="https://www.googleapis.com/auth/gmail.readonly",
        encrypted_refresh_token=encrypt_secret("refresh-gmail-secret"),
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


def test_fetch_gmail_rejects_write_method_name():
    with pytest.raises(WriteAttemptError):
        assert_readonly("gmail", "users.messages.modify")


@pytest.mark.asyncio
async def test_sync_posts_nothing_and_keeps_candidates_unselected(
    client: AsyncClient,
    auth_headers,
    session: AsyncSession,
    test_user,
    test_workspace,
    vault_dir,
    google_oauth_clients,
):
    await _connected_gmail(session, test_user, test_workspace)
    csv = b"date,description,amount\n2026-09-01,CARD 100,-10.00\n"
    page = SyncPage(
        items=[
            {
                "external_id": "m-sync-1",
                "thread_id": "t1",
                "received_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
                "from_address": "bank@example.com",
                "subject": "Your statement",
                "snippet": "See attached",
                "has_attachments": True,
                "attachments": [
                    {
                        "attachment_id": "a1",
                        "filename": "statement.csv",
                        "mime": "text/csv",
                        "data": csv,
                    }
                ],
            }
        ],
        next_cursor=None,
    )
    with (
        patch(
            "app.services.source_sync_service.refresh_access_token",
            AsyncMock(return_value=("access-token", None)),
        ),
        patch(
            "app.integrations.source_fetch.fetch_gmail_messages",
            AsyncMock(return_value=page),
        ),
    ):
        response = await client.post("/api/sources/gmail/sync", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["last_sync_result"] == "ok"
    assert body["status"] == "connected"

    documents = (await client.get("/api/documents", headers=auth_headers)).json()
    assert any(row["origin"] == "gmail" for row in documents)
    candidates = (await client.get("/api/review/candidates", headers=auth_headers)).json()
    assert candidates
    assert all(row["selected"] is False for row in candidates)
    assert all(row["status"] == "pending" for row in candidates)


@pytest.mark.asyncio
async def test_sync_refuses_when_disconnected(client: AsyncClient, auth_headers):
    response = await client.post("/api/sources/gmail/sync", headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_gmail_fetch_uses_get_only():
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            class _Resp:
                content = b"{}"
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    if "/messages/" in str(url):
                        return {
                            "id": "m1",
                            "threadId": "t1",
                            "snippet": "hi",
                            "payload": {
                                "headers": [
                                    {"name": "Subject", "value": "Invoice"},
                                    {"name": "From", "value": "a@example.com"},
                                    {"name": "Date", "value": "Tue, 1 Sep 2026 00:00:00 +0000"},
                                ],
                                "parts": [],
                            },
                        }
                    return {"messages": [{"id": "m1"}]}

            return _Resp()

        async def post(self, *args, **kwargs):
            raise AssertionError("source fetch must not POST")

    with patch("app.integrations.source_fetch.httpx.AsyncClient", _Client):
        page = await fetch_gmail_messages("token")
    assert page.items[0]["external_id"] == "m1"
    assert page.items[0]["subject"] == "Invoice"
