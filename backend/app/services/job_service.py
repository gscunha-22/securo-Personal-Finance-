import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.privacy import sanitize_error
from app.models.processing_job import JobAttempt, ProcessingJob

TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}
ACTIVE = {"queued", "running", "waiting_review"}


async def enqueue(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    job_type: str,
    idempotency_key: str,
    payload: dict,
    source_connection_id: uuid.UUID | None = None,
    priority: int = 100,
    correlation_id: str | None = None,
) -> ProcessingJob:
    existing = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.workspace_id == workspace_id,
            ProcessingJob.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing
    job = ProcessingJob(
        workspace_id=workspace_id,
        source_connection_id=source_connection_id,
        job_type=job_type,
        status="queued",
        priority=priority,
        payload=payload,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    session.add(job)
    await session.flush()
    return job


async def mark_running(session: AsyncSession, job: ProcessingJob) -> ProcessingJob:
    now = datetime.now(timezone.utc)
    job.status = "running"
    job.attempts += 1
    job.started_at = now
    job.locked_at = now
    job.lock_expires_at = now + timedelta(seconds=job.timeout_seconds)
    job.updated_at = now
    session.add(
        JobAttempt(job_id=job.id, attempt_number=job.attempts, status="running", started_at=now)
    )
    return job


async def finish(
    session: AsyncSession,
    job: ProcessingJob,
    status: str,
    error: str | None = None,
) -> ProcessingJob:
    now = datetime.now(timezone.utc)
    job.status = status
    job.finished_at = now
    job.locked_at = None
    job.lock_expires_at = None
    job.error = sanitize_error(error) if error else None
    job.updated_at = now
    if status == "failed" and job.attempts < job.max_attempts:
        job.status = "queued"
        job.next_retry_at = now + timedelta(seconds=min(300, 15 * (2 ** (job.attempts - 1))))
        job.finished_at = None
    return job


async def list_jobs(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    status: Optional[str] = None,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[ProcessingJob]:
    query = (
        select(ProcessingJob)
        .where(ProcessingJob.workspace_id == workspace_id)
        .options(
            load_only(
                ProcessingJob.job_type,
                ProcessingJob.status,
                ProcessingJob.attempts,
                ProcessingJob.error,
                ProcessingJob.created_at,
                ProcessingJob.started_at,
                ProcessingJob.finished_at,
            )
        )
    )
    if status:
        query = query.where(ProcessingJob.status == status)
    query = query.order_by(ProcessingJob.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(query)).scalars().all())


async def recover_abandoned(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.status == "running",
            ProcessingJob.lock_expires_at.is_not(None),
            ProcessingJob.lock_expires_at < now,
        )
        .options(
            load_only(
                ProcessingJob.status,
                ProcessingJob.locked_at,
                ProcessingJob.lock_expires_at,
                ProcessingJob.error,
                ProcessingJob.next_retry_at,
            )
        )
    )
    count = 0
    for job in result.scalars():
        job.status = "queued"
        job.locked_at = None
        job.lock_expires_at = None
        job.error = "Recovered abandoned job after lock timeout"
        job.next_retry_at = now
        count += 1
    return count


async def list_ready_queued(
    session: AsyncSession,
    *,
    job_type: str | None = None,
    limit: int = 20,
) -> list[ProcessingJob]:
    """Queued jobs whose retry time has arrived (or was never set)."""
    now = datetime.now(timezone.utc)
    query = select(ProcessingJob).where(
        ProcessingJob.status == "queued",
        or_(ProcessingJob.next_retry_at.is_(None), ProcessingJob.next_retry_at <= now),
    )
    if job_type:
        query = query.where(ProcessingJob.job_type == job_type)
    query = query.order_by(ProcessingJob.priority, ProcessingJob.created_at).limit(limit)
    return list((await session.execute(query)).scalars().all())
