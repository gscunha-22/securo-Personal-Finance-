"""Persistent document extraction, OCR, and connector sync jobs."""
from __future__ import annotations

import asyncio
import uuid

from app.core.database import make_worker_session_maker
from app.worker import celery_app


def _make_session_maker():
    """Create a fresh engine+session for the Celery worker event loop."""
    return make_worker_session_maker()


async def _process_document(job_id: str) -> None:
    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            from app.services.vault_service import process_extraction_job

            await process_extraction_job(session, uuid.UUID(job_id))
    finally:
        await engine.dispose()


async def _recover_abandoned() -> None:
    from app.services import job_service, source_sync_service
    from app.services.vault_service import process_extraction_job

    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            await job_service.recover_abandoned(session)
            await session.commit()
            ready = await job_service.list_ready_queued(session)
            for job in ready:
                if job.job_type == "extract_document":
                    await process_extraction_job(session, job.id)
                elif job.job_type.startswith("sync_"):
                    await source_sync_service.process_sync_job(session, job.id)
    finally:
        await engine.dispose()


async def _sync_connected_sources() -> None:
    from app.services import source_sync_service

    engine, session_maker = _make_session_maker()
    try:
        async with session_maker() as session:
            await source_sync_service.sync_all_connected(session)
    finally:
        await engine.dispose()


@celery_app.task(name="app.tasks.intelligence_tasks.process_document")
def process_document(job_id: str) -> None:
    asyncio.run(_process_document(job_id))


@celery_app.task(name="app.tasks.intelligence_tasks.recover_abandoned_jobs")
def recover_abandoned_jobs() -> None:
    asyncio.run(_recover_abandoned())


@celery_app.task(name="app.tasks.intelligence_tasks.sync_connected_sources")
def sync_connected_sources() -> None:
    asyncio.run(_sync_connected_sources())
