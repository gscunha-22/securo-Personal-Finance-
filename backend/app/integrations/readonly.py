"""Read-only adapters for Google Sheets, Gmail and Outlook.

Write APIs are not implemented on purpose. Tests assert that the adapters
expose only the listed methods.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.core.privacy import decrypt_secret, encrypt_secret, sanitize_error

READ_ONLY_SCOPES = {
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly",),
    "sheets": ("https://www.googleapis.com/auth/spreadsheets.readonly",),
    "outlook": ("https://graph.microsoft.com/Mail.Read",),
}

FORBIDDEN_GMAIL = {
    "users.messages.send",
    "users.messages.modify",
    "users.messages.trash",
    "users.messages.delete",
    "users.drafts.create",
    "users.labels.update",
}
FORBIDDEN_OUTLOOK = {
    "sendMail",
    "move",
    "delete",
    "createReply",
    "update",
}


class ReadOnlyMailAdapter(Protocol):
    provider: str

    def list_messages(self, cursor: str | None, query: str | None) -> dict: ...
    def get_message(self, message_id: str) -> dict: ...
    def download_attachment(self, message_id: str, attachment_id: str) -> bytes: ...


@dataclass
class SyncPage:
    items: list[dict]
    next_cursor: str | None
    partial: bool = False


class GmailReadAdapter:
    provider = "gmail"
    allowed_scopes = READ_ONLY_SCOPES["gmail"]

    def list_messages(self, cursor: str | None = None, query: str | None = None) -> SyncPage:
        raise NotConfiguredError("Gmail is not connected. OAuth consent is required.")

    def get_message(self, message_id: str) -> dict:
        raise NotConfiguredError("Gmail is not connected. OAuth consent is required.")

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        raise NotConfiguredError("Gmail is not connected. OAuth consent is required.")


class OutlookReadAdapter:
    provider = "outlook"
    allowed_scopes = READ_ONLY_SCOPES["outlook"]

    def list_messages(self, cursor: str | None = None, query: str | None = None) -> SyncPage:
        raise NotConfiguredError("Outlook is not connected. OAuth consent is required.")

    def get_message(self, message_id: str) -> dict:
        raise NotConfiguredError("Outlook is not connected. OAuth consent is required.")

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        raise NotConfiguredError("Outlook is not connected. OAuth consent is required.")


class SheetsReadAdapter:
    provider = "sheets"
    allowed_scopes = READ_ONLY_SCOPES["sheets"]

    def list_spreadsheets(self) -> list[dict]:
        raise NotConfiguredError("Google Sheets is not connected. OAuth consent is required.")

    def preview(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        raise NotConfiguredError("Google Sheets is not connected. OAuth consent is required.")


class NotConfiguredError(RuntimeError):
    pass


class WriteAttemptError(RuntimeError):
    pass


def assert_readonly(provider: str, method: str) -> None:
    if provider == "gmail" and method in FORBIDDEN_GMAIL:
        raise WriteAttemptError(f"Gmail method {method} is forbidden")
    if provider == "outlook" and method in FORBIDDEN_OUTLOOK:
        raise WriteAttemptError(f"Outlook method {method} is forbidden")
    if method.lower() in {"send", "delete", "trash", "archive", "modify", "move"}:
        raise WriteAttemptError(f"{provider} write method {method} is forbidden")


async def ingest_mock_messages(
    session,
    *,
    workspace_id,
    source_connection_id,
    provider: str,
    messages: list[dict],
):
    """Used by tests and by a real sync once OAuth exists. Dedupes on external_id."""
    from sqlalchemy import select

    from app.models.vault import EmailMessage, SyncCursor
    from app.services import audit_service

    stored = 0
    for message in messages:
        assert_readonly(provider, "list")
        existing = await session.scalar(
            select(EmailMessage).where(
                EmailMessage.workspace_id == workspace_id,
                EmailMessage.provider == provider,
                EmailMessage.external_id == message["external_id"],
            )
        )
        if existing:
            continue
        session.add(
            EmailMessage(
                workspace_id=workspace_id,
                source_connection_id=source_connection_id,
                provider=provider,
                external_id=message["external_id"],
                thread_id=message.get("thread_id"),
                received_at=message.get("received_at"),
                from_address=message.get("from_address"),
                subject=message.get("subject"),
                snippet=(message.get("snippet") or "")[:1000],
                has_attachments=bool(message.get("has_attachments")),
            )
        )
        stored += 1
    cursor = await session.scalar(
        select(SyncCursor).where(
            SyncCursor.source_connection_id == source_connection_id,
            SyncCursor.cursor_key == "messages",
        )
    )
    value = messages[-1]["external_id"] if messages else ""
    if cursor:
        cursor.cursor_value = value
        cursor.updated_at = datetime.now(timezone.utc)
    elif value:
        session.add(
            SyncCursor(
                source_connection_id=source_connection_id,
                workspace_id=workspace_id,
                cursor_key="messages",
                cursor_value=value,
            )
        )
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=None,
        action=f"{provider}.sync",
        entity_type="source_connection",
        entity_id=source_connection_id,
        summary=f"Read {stored} new messages without modifying the mailbox",
    )
    return stored


def store_refresh_token(raw: str) -> str:
    return encrypt_secret(raw)


def load_refresh_token(stored: str) -> str:
    return decrypt_secret(stored)


def public_connector_status(status: str, last_error: str | None) -> dict:
    return {
        "status": status,
        "error": sanitize_error(last_error) if last_error else None,
    }
