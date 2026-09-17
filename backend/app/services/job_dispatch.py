"""Hand queued intelligence jobs to Celery.

The jobs table stays the source of truth. Tests process inline because
pytest does not run a worker. A failed broker publish leaves the queued
row for recover_abandoned.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processing_job import ProcessingJob

logger = logging.getLogger(__name__)

EXTRACT_TASK = "app.tasks.intelligence_tasks.process_document"
SYNC_TASK = "app.tasks.intelligence_tasks.process_sync"


def in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _task_name(job: ProcessingJob) -> str:
    if job.job_type == "extract_document":
        return EXTRACT_TASK
    if job.job_type.startswith("sync_"):
        return SYNC_TASK
    raise ValueError(f"Cannot dispatch job type {job.job_type}")


async def _run_inline(session: AsyncSession, job: ProcessingJob) -> ProcessingJob:
    if job.job_type == "extract_document":
        from app.services.vault_service import process_extraction_job

        return await process_extraction_job(session, job.id)
    if job.job_type.startswith("sync_"):
        from app.services import source_sync_service

        return await source_sync_service.process_sync_job(session, job.id)
    raise ValueError(f"Cannot dispatch job type {job.job_type}")


def publish(job: ProcessingJob) -> None:
    from app.worker import celery_app

    try:
        celery_app.send_task(_task_name(job), args=[str(job.id)])
    except Exception:
        logger.exception(
            "Celery dispatch failed for job %s; queued row remains for recover_abandoned",
            job.id,
        )


async def dispatch_or_run(
    session: AsyncSession,
    job: ProcessingJob,
    *,
    run_inline_in_tests: bool = True,
) -> ProcessingJob:
    if in_pytest():
        if run_inline_in_tests:
            return await _run_inline(session, job)
        return job
    publish(job)
    return job
