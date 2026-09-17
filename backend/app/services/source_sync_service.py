"""Turn a connected read-only source into vault documents.

Nothing is posted to the ledger. Attachments and sheet exports go through
the same unselected candidate path as a manual upload.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.privacy import decrypt_secret, sanitize_error
from app.integrations import source_fetch
from app.integrations.readonly import ingest_mock_messages
from app.integrations.source_oauth import refresh_access_token
from app.models.processing_job import ProcessingJob
from app.models.vault import SourceConnection
from app.services import job_service, vault_service


async def enqueue_sync(
    session: AsyncSession,
    connection: SourceConnection,
) -> ProcessingJob:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return await job_service.enqueue(
        session,
        workspace_id=connection.workspace_id,
        job_type=f"sync_{connection.provider}",
        idempotency_key=f"sync:{connection.id}:{stamp}",
        payload={"source_connection_id": str(connection.id)},
        source_connection_id=connection.id,
    )


async def process_sync_job(session: AsyncSession, job_id: uuid.UUID) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
    )
    if job is None:
        raise LookupError("Job not found")
    if job.status in {"completed", "partially_completed", "cancelled"}:
        return job
    now = datetime.now(timezone.utc)
    if job.status == "running" and job.lock_expires_at is not None and job.lock_expires_at > now:
        return job
    await job_service.mark_running(session, job)
    await session.commit()
    try:
        source_id = uuid.UUID(job.payload["source_connection_id"])
        connection = await session.get(SourceConnection, source_id)
        if connection is None:
            raise LookupError("Source is not connected")
        result = await sync_connection(session, connection)
        status = "partially_completed" if result.get("errors") else "completed"
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            raise LookupError("Job not found")
        await job_service.finish(session, job, status)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        job = await session.get(ProcessingJob, job_id)
        if job is not None:
            await job_service.finish(session, job, "failed", error=str(exc))
            await session.commit()
        else:
            raise
    resolved = await session.get(ProcessingJob, job_id)
    if resolved is None:
        raise LookupError("Job not found")
    return resolved


async def sync_connection(session: AsyncSession, connection: SourceConnection) -> dict:
    if connection.status != "connected" or not connection.encrypted_refresh_token:
        raise ValueError("Source is not connected")
    refresh = decrypt_secret(connection.encrypted_refresh_token)
    access, expires_at = await refresh_access_token(connection.provider, refresh)
    connection.token_expires_at = expires_at
    stored_messages = 0
    stored_documents = 0
    errors: list[str] = []
    try:
        if connection.provider == "gmail":
            page = await source_fetch.fetch_gmail_messages(access)
            stored_messages = await ingest_mock_messages(
                session,
                workspace_id=connection.workspace_id,
                source_connection_id=connection.id,
                provider="gmail",
                messages=page.items,
            )
            stored_documents = await _store_attachments(
                session, connection, page.items, errors
            )
        elif connection.provider == "outlook":
            page = await source_fetch.fetch_outlook_messages(access)
            stored_messages = await ingest_mock_messages(
                session,
                workspace_id=connection.workspace_id,
                source_connection_id=connection.id,
                provider="outlook",
                messages=page.items,
            )
            stored_documents = await _store_attachments(
                session, connection, page.items, errors
            )
        elif connection.provider == "sheets":
            page = await source_fetch.fetch_sheet_files(access)
            for sheet in page.items:
                if not sheet.get("data"):
                    continue
                stored_documents += await _store_bytes(
                    session,
                    connection,
                    filename=sheet["filename"],
                    declared_mime=sheet["mime"],
                    data=sheet["data"],
                    errors=errors,
                )
        else:
            raise ValueError(f"Unknown source provider: {connection.provider}")
        connection.last_sync_at = datetime.now(timezone.utc)
        connection.last_sync_result = "partial" if errors else "ok"
        connection.last_error = sanitize_error("; ".join(errors)) if errors else None
        await session.commit()
        return {
            "messages": stored_messages,
            "documents": stored_documents,
            "errors": errors,
        }
    except Exception as exc:
        connection.last_sync_at = datetime.now(timezone.utc)
        connection.last_sync_result = "error"
        connection.last_error = sanitize_error(str(exc))
        await session.commit()
        raise


async def _store_attachments(
    session: AsyncSession,
    connection: SourceConnection,
    messages: list[dict],
    errors: list[str],
) -> int:
    stored = 0
    for message in messages:
        for attachment in message.get("attachments") or []:
            data = attachment.get("data") or b""
            if not data:
                continue
            stored += await _store_bytes(
                session,
                connection,
                filename=attachment.get("filename") or "attachment",
                declared_mime=attachment.get("mime") or "application/octet-stream",
                data=data,
                errors=errors,
            )
    return stored


async def _store_bytes(
    session: AsyncSession,
    connection: SourceConnection,
    *,
    filename: str,
    declared_mime: str,
    data: bytes,
    errors: list[str],
) -> int:
    try:
        document = await vault_service.upload_document(
            session,
            workspace_id=connection.workspace_id,
            user_id=connection.user_id,
            filename=filename,
            declared_mime=declared_mime,
            data=data,
            origin=connection.provider,
            source_connection_id=connection.id,
        )
        return 0 if document is None else 1
    except ValueError as exc:
        errors.append(sanitize_error(str(exc)))
        return 0


async def sync_all_connected(session: AsyncSession) -> int:
    result = await session.execute(
        select(SourceConnection).where(
            SourceConnection.status == "connected",
            SourceConnection.encrypted_refresh_token.is_not(None),
        )
    )
    count = 0
    for connection in result.scalars():
        job = await enqueue_sync(session, connection)
        await session.commit()
        await process_sync_job(session, job.id)
        count += 1
    return count
