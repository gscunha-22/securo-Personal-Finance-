"""Persistent document extraction, OCR, and connector sync jobs."""
from app.worker import celery_app


@celery_app.task(name="app.tasks.intelligence_tasks.process_document")
def process_document(job_id: str) -> None:
    import asyncio
    import uuid

    from app.core.database import async_session_maker
    from app.services.vault_service import process_extraction_job

    async def _run() -> None:
        async with async_session_maker() as session:
            await process_extraction_job(session, uuid.UUID(job_id))

    asyncio.run(_run())


@celery_app.task(name="app.tasks.intelligence_tasks.recover_abandoned_jobs")
def recover_abandoned_jobs() -> None:
    import asyncio

    from app.core.database import async_session_maker
    from app.services import job_service

    async def _run() -> None:
        async with async_session_maker() as session:
            await job_service.recover_abandoned(session)
            await session.commit()

    asyncio.run(_run())
