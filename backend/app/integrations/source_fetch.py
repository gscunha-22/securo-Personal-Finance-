"""Live read-only HTTP for Gmail, Sheets and Outlook.

Every call is GET. Write method names are rejected before the request.
Amounts and dates are taken from the provider payload, never invented.
"""
from __future__ import annotations

import base64
import csv
import io
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.integrations.readonly import SyncPage, assert_readonly

GMAIL_MESSAGES = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
GRAPH_MESSAGES = "https://graph.microsoft.com/v1.0/me/messages"

PAGE_SIZE = 20


async def _get_json(url: str, access_token: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def _gmail_header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers") or []:
        if str(header.get("name") or "").lower() == name.lower():
            return str(header.get("value") or "")
    return ""


def _parse_email_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _decode_gmail_data(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _collect_gmail_parts(payload: dict[str, Any], acc: list[dict[str, Any]]) -> None:
    filename = payload.get("filename")
    body = payload.get("body") or {}
    attach_id = body.get("attachmentId")
    mime = payload.get("mimeType") or "application/octet-stream"
    if filename and attach_id:
        acc.append(
            {
                "attachment_id": str(attach_id),
                "filename": str(filename),
                "mime": str(mime),
            }
        )
    for part in payload.get("parts") or []:
        _collect_gmail_parts(part, acc)


async def fetch_gmail_messages(access_token: str, cursor: str | None = None) -> SyncPage:
    assert_readonly("gmail", "users.messages.list")
    params = {"maxResults": str(PAGE_SIZE), "q": "has:attachment"}
    if cursor:
        params["pageToken"] = cursor
    listing = await _get_json(GMAIL_MESSAGES, access_token, params)
    items: list[dict[str, Any]] = []
    for stub in listing.get("messages") or []:
        message_id = stub.get("id")
        if not message_id:
            continue
        assert_readonly("gmail", "users.messages.get")
        detail = await _get_json(f"{GMAIL_MESSAGES}/{message_id}", access_token, {"format": "full"})
        payload = detail.get("payload") or {}
        attachments: list[dict[str, Any]] = []
        _collect_gmail_parts(payload, attachments)
        for attachment in attachments:
            assert_readonly("gmail", "users.messages.attachments.get")
            blob = await _get_json(
                f"{GMAIL_MESSAGES}/{message_id}/attachments/{attachment['attachment_id']}",
                access_token,
            )
            attachment["data"] = _decode_gmail_data(str(blob.get("data") or ""))
        items.append(
            {
                "external_id": str(message_id),
                "thread_id": detail.get("threadId"),
                "received_at": _parse_email_date(_gmail_header(payload, "Date")),
                "from_address": _gmail_header(payload, "From")[:500],
                "subject": _gmail_header(payload, "Subject")[:1000],
                "snippet": str(detail.get("snippet") or "")[:1000],
                "has_attachments": bool(attachments),
                "attachments": attachments,
            }
        )
    return SyncPage(items=items, next_cursor=listing.get("nextPageToken"))


def _graph_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


async def fetch_outlook_messages(access_token: str, cursor: str | None = None) -> SyncPage:
    assert_readonly("outlook", "list")
    url = cursor or (
        f"{GRAPH_MESSAGES}?$top={PAGE_SIZE}"
        "&$filter=hasAttachments eq true"
        "&$select=id,subject,from,receivedDateTime,hasAttachments,bodyPreview,conversationId"
    )
    listing = await _get_json(url, access_token)
    items: list[dict[str, Any]] = []
    for row in listing.get("value") or []:
        message_id = row.get("id")
        if not message_id:
            continue
        assert_readonly("outlook", "list")
        attachments_payload = await _get_json(
            f"{GRAPH_MESSAGES}/{message_id}/attachments",
            access_token,
        )
        attachments: list[dict[str, Any]] = []
        for attachment in attachments_payload.get("value") or []:
            if attachment.get("@odata.type") == "#microsoft.graph.fileAttachment":
                raw = str(attachment.get("contentBytes") or "")
                padded = raw + "=" * (-len(raw) % 4)
                attachments.append(
                    {
                        "attachment_id": str(attachment.get("id") or ""),
                        "filename": str(attachment.get("name") or "attachment"),
                        "mime": str(attachment.get("contentType") or "application/octet-stream"),
                        "data": base64.b64decode(padded.encode("ascii")) if raw else b"",
                    }
                )
        sender = ((row.get("from") or {}).get("emailAddress") or {})
        items.append(
            {
                "external_id": str(message_id),
                "thread_id": row.get("conversationId"),
                "received_at": _graph_datetime(row.get("receivedDateTime")),
                "from_address": str(sender.get("address") or "")[:500],
                "subject": str(row.get("subject") or "")[:1000],
                "snippet": str(row.get("bodyPreview") or "")[:1000],
                "has_attachments": bool(attachments),
                "attachments": attachments,
            }
        )
    return SyncPage(items=items, next_cursor=listing.get("@odata.nextLink"))


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


async def fetch_sheet_files(access_token: str, cursor: str | None = None) -> SyncPage:
    assert_readonly("sheets", "list")
    params = {
        "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        "fields": "nextPageToken,files(id,name)",
        "pageSize": str(min(PAGE_SIZE, 10)),
    }
    if cursor:
        params["pageToken"] = cursor
    listing = await _get_json(DRIVE_FILES, access_token, params)
    items: list[dict[str, Any]] = []
    for file in listing.get("files") or []:
        spreadsheet_id = file.get("id")
        if not spreadsheet_id:
            continue
        meta = await _get_json(
            f"{SHEETS_API}/{spreadsheet_id}",
            access_token,
            {"fields": "sheets.properties.title"},
        )
        titles = [
            str(sheet.get("properties", {}).get("title") or "Sheet1")
            for sheet in (meta.get("sheets") or [])
        ]
        title = titles[0] if titles else "Sheet1"
        values_payload = await _get_json(
            f"{SHEETS_API}/{spreadsheet_id}/values/{title}",
            access_token,
        )
        values = values_payload.get("values") or []
        items.append(
            {
                "external_id": str(spreadsheet_id),
                "filename": f"{file.get('name') or spreadsheet_id}.csv",
                "mime": "text/csv",
                "data": _csv_bytes([[str(cell) for cell in row] for row in values]) if values else b"",
            }
        )
    return SyncPage(items=items, next_cursor=listing.get("nextPageToken"))
