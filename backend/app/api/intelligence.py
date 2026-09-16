import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.rate_limit import RateLimiter
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.services import job_service, vault_service
from app.services.debt_service import (
    AmortizeBody,
    CashPlanBody,
    DebtCreate,
    DebtInstallmentCreate,
    DebtPaymentCreate,
    DebtRead,
    DebtUpdate,
    ExampleBody,
    OfferCreate,
    PmtHintBody,
    StepsBody,
    add_installment,
    add_payment,
    create_debt,
    create_offer,
    delete_debt,
    delete_offer,
    get_plan,
    list_debts,
    pmt_hint,
    seed_example,
    simulate_amortize,
    update_debt,
    update_steps,
    upsert_cash,
)
from app.models.audit import AuditEvent, AppNotification
from app.models.processing_job import ProcessingJob
from app.models.vault import SourceConnection, VaultDocument
from sqlalchemy import select

upload_rate_limit = RateLimiter(max_requests=20, window_seconds=60)

router = APIRouter(tags=["intelligence"])


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: str
    status: str
    origin: str
    filename: str
    mime: str
    sha256: str
    byte_size: int
    created_at: datetime


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    selected: bool
    status: str
    description: str
    amount: Decimal
    currency: str
    competence_date: date
    payment_date: Optional[date]
    txn_type: str
    payee: Optional[str]
    locator: Optional[str]
    confidence: Decimal
    duplicate_of_transaction_id: Optional[uuid.UUID]
    suggested_category: Optional[str]
    suggestion_rationale: Optional[str]
    suggestion_confidence: Optional[Decimal]
    posted_transaction_id: Optional[uuid.UUID]


class DecisionBody(BaseModel):
    candidate_ids: list[uuid.UUID]
    decision: str
    account_id: Optional[uuid.UUID] = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    status: str
    attempts: int
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    entity_type: str
    entity_id: Optional[str]
    summary: str
    created_at: datetime


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    display_name: str
    status: str
    granted_scopes: Optional[str]
    last_sync_at: Optional[datetime]
    last_sync_result: Optional[str]
    last_error: Optional[str]


class AiSuggestBody(BaseModel):
    category: Optional[str] = None
    payee: Optional[str] = None
    description: Optional[str] = None
    rationale: str
    confidence: float
    amount: Optional[Decimal] = None
    date: Optional[date] = None


def _document_read(doc: VaultDocument) -> DocumentRead:
    stored = doc.stored_object
    return DocumentRead(
        id=doc.id,
        document_type=doc.document_type,
        status=doc.status,
        origin=doc.origin,
        filename=stored.original_filename,
        mime=stored.detected_mime,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        created_at=doc.created_at,
    )


@router.post("/api/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    account_id: Optional[uuid.UUID] = Form(None),
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
    _: None = Depends(upload_rate_limit),
):
    data = await file.read()
    try:
        document = await vault_service.upload_document(
            session,
            workspace_id=ctx.workspace.id,
            user_id=ctx.user_id,
            filename=file.filename or "upload",
            declared_mime=file.content_type or "application/octet-stream",
            data=data,
            account_id=account_id,
            correlation_id=getattr(ctx, "correlation_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stored = await vault_service.get_document(session, ctx.workspace.id, document.id)
    if stored is None:
        raise HTTPException(status_code=500, detail="Document was stored but could not be read")
    return _document_read(stored)


@router.get("/api/documents", response_model=list[DocumentRead])
async def list_documents(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    docs = await vault_service.list_documents(session, ctx.workspace.id)
    return [_document_read(doc) for doc in docs]


@router.get("/api/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    document = await vault_service.get_document(session, ctx.workspace.id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_read(document)


@router.get("/api/documents/{document_id}/file")
async def download_document(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        stored, data = await vault_service.download_original(session, ctx.workspace.id, document_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(
        content=data,
        media_type=stored.detected_mime,
        headers={
            "Content-Disposition": f'inline; filename="{stored.original_filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/api/documents/{document_id}/fields")
async def document_fields(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    document = await vault_service.get_document(session, ctx.workspace.id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    fields = []
    for extraction in document.extractions:
        for field in extraction.fields:
            fields.append(
                {
                    "name": field.name,
                    "value": field.human_correction or field.value,
                    "extracted_value": field.value,
                    "locator": field.locator,
                    "method": field.method,
                    "confidence": str(field.confidence),
                    "human_correction": field.human_correction,
                }
            )
    return fields


@router.get("/api/review/candidates", response_model=list[CandidateRead])
async def list_candidates(
    status: Optional[str] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await vault_service.list_candidates(session, ctx.workspace.id, status)


@router.post("/api/review/decisions")
async def decide(
    body: DecisionBody,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await vault_service.decide_candidates(
            session,
            workspace_id=ctx.workspace.id,
            user_id=ctx.user_id,
            candidate_ids=body.candidate_ids,
            decision=body.decision,
            account_id=body.account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/documents/{document_id}/revert")
async def revert_document(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    count = await vault_service.revert_import(
        session,
        workspace_id=ctx.workspace.id,
        user_id=ctx.user_id,
        document_id=document_id,
    )
    return {"reverted": count}


@router.get("/api/jobs", response_model=list[JobRead])
async def list_jobs(
    status: Optional[str] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await job_service.list_jobs(session, ctx.workspace.id, status)


@router.post("/api/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    job = await session.get(ProcessingJob, job_id)
    if not job or job.workspace_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type == "extract_document":
        job.status = "queued"
        await session.commit()
        return await vault_service.process_extraction_job(session, job.id)
    raise HTTPException(status_code=400, detail="This job type cannot be retried here")


@router.get("/api/audit", response_model=list[AuditRead])
async def list_audit(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == ctx.workspace.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(200)
    )
    return list(result.scalars().all())


@router.get("/api/notifications")
async def list_notifications(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(AppNotification)
        .where(
            AppNotification.workspace_id == ctx.workspace.id,
            AppNotification.user_id == ctx.user_id,
        )
        .order_by(AppNotification.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "title": item.title,
            "body": item.body,
            "is_read": item.is_read,
            "created_at": item.created_at,
        }
        for item in result.scalars()
    ]


@router.get("/api/sources", response_model=list[SourceRead])
async def list_sources(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    from app.core.config import get_settings
    from app.integrations.readonly import READ_ONLY_SCOPES

    result = await session.execute(
        select(SourceConnection).where(SourceConnection.workspace_id == ctx.workspace.id)
    )
    rows = list(result.scalars().all())
    settings = get_settings()
    by_provider = {row.provider: row for row in rows}
    out: list[SourceRead] = []
    for provider, configured in (
        ("gmail", bool(settings.google_client_id)),
        ("sheets", bool(settings.google_client_id)),
        ("outlook", bool(settings.microsoft_client_id)),
    ):
        row = by_provider.get(provider)
        if row:
            out.append(SourceRead.model_validate(row))
            continue
        out.append(
            SourceRead(
                id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                provider=provider,
                display_name=provider.title(),
                status="not_configured" if not configured else "awaiting_consent",
                granted_scopes=" ".join(READ_ONLY_SCOPES[provider]),
                last_sync_at=None,
                last_sync_result=None,
                last_error="OAuth consent from the owner is required" if configured else "Client id is not set",
            )
        )
    return out


@router.post("/api/ai/suggestions")
async def validate_ai_suggestion(
    body: AiSuggestBody,
    ctx: WorkspaceContext = Depends(current_workspace),
):
    _ = ctx
    try:
        return vault_service.ai_validate_suggestion(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/debts", response_model=list[DebtRead])
async def debts_list(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await list_debts(session, ctx.workspace.id)


@router.post("/api/debts", response_model=DebtRead, status_code=status.HTTP_201_CREATED)
async def debts_create(
    data: DebtCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await create_debt(session, ctx.workspace.id, ctx.user_id, data)


@router.patch("/api/debts/{debt_id}", response_model=DebtRead)
async def debts_update(
    debt_id: uuid.UUID,
    data: DebtUpdate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    debt = await update_debt(session, ctx.workspace.id, ctx.user_id, debt_id, data)
    if not debt:
        raise HTTPException(status_code=404, detail="Debt not found")
    return debt


@router.post("/api/debts/{debt_id}/payments")
async def debts_payment(
    debt_id: uuid.UUID,
    data: DebtPaymentCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    payment = await add_payment(session, ctx.workspace.id, ctx.user_id, debt_id, data)
    if not payment:
        raise HTTPException(status_code=404, detail="Debt not found")
    return {"id": payment.id, "outstanding_balance": str(payment.debt.outstanding_balance) if payment.debt else None}


@router.post("/api/debts/{debt_id}/installments")
async def debts_installment(
    debt_id: uuid.UUID,
    data: DebtInstallmentCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    row = await add_installment(session, ctx.workspace.id, debt_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Debt not found")
    return {"id": row.id}


@router.delete("/api/debts/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def debts_delete(
    debt_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    ok = await delete_debt(session, ctx.workspace.id, ctx.user_id, debt_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Debt not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/renegotiation")
async def renegotiation_plan(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await get_plan(session, ctx.workspace.id)


@router.put("/api/renegotiation/cash")
async def renegotiation_cash(
    data: CashPlanBody,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await upsert_cash(session, ctx.workspace.id, ctx.user_id, data)


@router.post("/api/renegotiation/offers")
async def renegotiation_offer_create(
    data: OfferCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await create_offer(session, ctx.workspace.id, ctx.user_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/renegotiation/offers/{offer_id}")
async def renegotiation_offer_delete(
    offer_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    plan = await delete_offer(session, ctx.workspace.id, ctx.user_id, offer_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return plan


@router.put("/api/renegotiation/steps")
async def renegotiation_steps(
    data: StepsBody,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    return await update_steps(session, ctx.workspace.id, ctx.user_id, data)


@router.post("/api/renegotiation/amortize")
async def renegotiation_amortize(
    data: AmortizeBody,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await simulate_amortize(session, ctx.workspace.id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/renegotiation/pmt-hint")
async def renegotiation_pmt_hint(
    data: PmtHintBody,
    ctx: WorkspaceContext = Depends(current_workspace),
):
    _ = ctx
    return pmt_hint(data)


@router.post("/api/renegotiation/example")
async def renegotiation_example(
    data: ExampleBody,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await seed_example(session, ctx.workspace.id, ctx.user_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
