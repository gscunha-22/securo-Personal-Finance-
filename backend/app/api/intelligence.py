import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.database import get_async_session
from app.core.privacy import content_disposition, encrypt_secret
from app.core.rate_limit import RateLimiter
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.services import audit_service, job_service, oauth_state, vault_service
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
    interpretation_version: int
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


class SourceConnectRead(BaseModel):
    authorization_url: str
    redirect_uri: str
    scopes: str


class SourceCallbackBody(BaseModel):
    code: str
    state: str


class AiSuggestBody(BaseModel):
    category: Optional[str] = None
    payee: Optional[str] = None
    description: Optional[str] = None
    rationale: str
    confidence: float
    amount: Optional[Decimal] = None
    date: Optional[date] = None


def _document_read(doc: VaultDocument, interpretation_version: int = 1) -> DocumentRead:
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
        interpretation_version=interpretation_version,
        created_at=doc.created_at,
    )


async def _document_reads(
    session: AsyncSession, docs: list[VaultDocument]
) -> list[DocumentRead]:
    versions = await vault_service.latest_interpretation_versions(
        session, [doc.id for doc in docs]
    )
    return [_document_read(doc, versions.get(doc.id, 1)) for doc in docs]


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
    reads = await _document_reads(session, [stored])
    return reads[0]


@router.get("/api/documents", response_model=list[DocumentRead])
async def list_documents(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    docs = await vault_service.list_documents(
        session, ctx.workspace.id, limit=limit, offset=offset
    )
    return await _document_reads(session, docs)


@router.get("/api/documents/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    document = await vault_service.get_document(session, ctx.workspace.id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    reads = await _document_reads(session, [document])
    return reads[0]


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
            "Content-Disposition": content_disposition("inline", stored.original_filename),
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/api/documents/{document_id}/fields")
async def document_fields(
    document_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    fields = await vault_service.list_extracted_fields(session, ctx.workspace.id, document_id)
    if fields is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return [
        {
            "name": field.name,
            "value": field.human_correction or field.value,
            "extracted_value": field.value,
            "locator": field.locator,
            "method": field.method,
            "confidence": str(field.confidence),
            "human_correction": field.human_correction,
        }
        for field in fields
    ]


@router.get("/api/review/candidates", response_model=list[CandidateRead])
async def list_candidates(
    status: Optional[str] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(500, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return await vault_service.list_candidates(
        session, ctx.workspace.id, status, limit=limit, offset=offset
    )


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
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await job_service.list_jobs(
        session, ctx.workspace.id, status, limit=limit, offset=offset
    )


@router.post("/api/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    job = await session.get(ProcessingJob, job_id)
    if not job or job.workspace_id != ctx.workspace.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.job_type == "extract_document" or job.job_type.startswith("sync_"):
        job.status = "queued"
        await session.commit()
        from app.services import job_dispatch

        return await job_dispatch.dispatch_or_run(session, job)
    raise HTTPException(status_code=400, detail="This job type cannot be retried here")


@router.get("/api/audit", response_model=list[AuditRead])
async def list_audit(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    result = await session.execute(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == ctx.workspace.id)
        .options(
            load_only(
                AuditEvent.action,
                AuditEvent.entity_type,
                AuditEvent.entity_id,
                AuditEvent.summary,
                AuditEvent.created_at,
            )
        )
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get("/api/notifications")
async def list_notifications(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(50, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    result = await session.execute(
        select(AppNotification)
        .where(
            AppNotification.workspace_id == ctx.workspace.id,
            AppNotification.user_id == ctx.user_id,
        )
        .options(
            load_only(
                AppNotification.kind,
                AppNotification.title,
                AppNotification.body,
                AppNotification.is_read,
                AppNotification.created_at,
            )
        )
        .order_by(AppNotification.created_at.desc())
        .limit(limit)
        .offset(offset)
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
        select(SourceConnection)
        .where(SourceConnection.workspace_id == ctx.workspace.id)
        .options(
            load_only(
                SourceConnection.provider,
                SourceConnection.display_name,
                SourceConnection.status,
                SourceConnection.granted_scopes,
                SourceConnection.last_sync_at,
                SourceConnection.last_sync_result,
                SourceConnection.last_error,
            )
        )
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


@router.post("/api/sources/{provider}/connect", response_model=SourceConnectRead)
async def connect_source(
    provider: str,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
):
    from app.integrations.source_oauth import (
        PROVIDERS,
        authorization_url,
        client_configured,
        redirect_uri,
        requested_scopes,
    )

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown source provider")
    if not client_configured(provider):
        raise HTTPException(status_code=409, detail="Client id is not set")
    state = await oauth_state.store_state(
        {
            "user_id": str(ctx.user_id),
            "workspace_id": str(ctx.workspace.id),
            "provider": provider,
            "flow": "source_readonly",
        }
    )
    try:
        url = authorization_url(provider, state)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SourceConnectRead(
        authorization_url=url,
        redirect_uri=redirect_uri(),
        scopes=" ".join(requested_scopes(provider)),
    )


@router.post("/api/sources/callback", response_model=SourceRead)
async def source_oauth_callback(
    body: SourceCallbackBody,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    from app.integrations.readonly import WriteAttemptError
    from app.integrations.source_oauth import exchange_authorization_code
    from app.core.privacy import sanitize_error

    stored = await oauth_state.consume_state(body.state)
    if not stored or stored.get("flow") != "source_readonly":
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if stored.get("workspace_id") != str(ctx.workspace.id) or stored.get("user_id") != str(
        ctx.user_id
    ):
        raise HTTPException(status_code=400, detail="OAuth state does not match this session")
    provider = stored.get("provider")
    if provider not in ("gmail", "sheets", "outlook"):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    try:
        bundle = await exchange_authorization_code(provider, body.code)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WriteAttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=sanitize_error(str(exc))) from exc

    result = await session.execute(
        select(SourceConnection).where(
            SourceConnection.workspace_id == ctx.workspace.id,
            SourceConnection.provider == provider,
        )
    )
    row = result.scalars().first()
    if row is None:
        row = SourceConnection(
            user_id=ctx.user_id,
            workspace_id=ctx.workspace.id,
            provider=provider,
            display_name=bundle.display_name,
        )
        session.add(row)
        await session.flush()
    row.user_id = ctx.user_id
    row.display_name = bundle.display_name
    row.external_account_id = bundle.external_account_id
    row.status = "connected"
    row.granted_scopes = bundle.granted_scopes
    row.consent_at = datetime.now(timezone.utc)
    row.encrypted_refresh_token = encrypt_secret(bundle.refresh_token)
    row.token_expires_at = bundle.expires_at
    row.last_error = None
    row.last_sync_result = None
    await audit_service.record(
        session,
        workspace_id=ctx.workspace.id,
        actor_user_id=ctx.user_id,
        action="source.connected",
        entity_type="source_connection",
        entity_id=row.id,
        summary=f"{provider} connected read-only",
        extra={"provider": provider, "scopes": bundle.granted_scopes},
    )
    await session.commit()
    await session.refresh(row)
    from app.services import job_dispatch, source_sync_service

    job = await source_sync_service.enqueue_sync(session, row)
    await session.commit()
    await job_dispatch.dispatch_or_run(session, job, run_inline_in_tests=False)
    await session.refresh(row)
    return SourceRead.model_validate(row)


@router.post("/api/sources/{provider}/disconnect", response_model=SourceRead)
async def disconnect_source(
    provider: str,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    from app.integrations.source_oauth import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown source provider")
    result = await session.execute(
        select(SourceConnection).where(
            SourceConnection.workspace_id == ctx.workspace.id,
            SourceConnection.provider == provider,
        )
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Source is not connected")
    row.status = "disconnected"
    row.encrypted_refresh_token = None
    row.granted_scopes = None
    row.last_error = None
    await audit_service.record(
        session,
        workspace_id=ctx.workspace.id,
        actor_user_id=ctx.user_id,
        action="source.disconnected",
        entity_type="source_connection",
        entity_id=row.id,
        summary=f"{provider} disconnected",
        extra={"provider": provider},
    )
    await session.commit()
    await session.refresh(row)
    return SourceRead.model_validate(row)


@router.post("/api/sources/{provider}/sync", response_model=SourceRead)
async def sync_source(
    provider: str,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    from app.integrations.source_oauth import PROVIDERS
    from app.services import source_sync_service

    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown source provider")
    result = await session.execute(
        select(SourceConnection).where(
            SourceConnection.workspace_id == ctx.workspace.id,
            SourceConnection.provider == provider,
        )
    )
    row = result.scalars().first()
    if row is None or row.status != "connected" or not row.encrypted_refresh_token:
        raise HTTPException(status_code=409, detail="Source is not connected")
    job = await source_sync_service.enqueue_sync(session, row)
    await session.commit()
    from app.services import job_dispatch

    try:
        await job_dispatch.dispatch_or_run(session, job)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.refresh(row)
    return SourceRead.model_validate(row)


@router.post("/api/ai/suggestions")
async def validate_ai_suggestion(
    body: AiSuggestBody,
    ctx: WorkspaceContext = Depends(current_workspace),
):
    _ = ctx
    try:
        return vault_service.ai_validate_suggestion(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/debts", response_model=list[DebtRead])
async def debts_list(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await list_debts(session, ctx.workspace.id, limit=limit, offset=offset)


@router.post("/api/debts", response_model=DebtRead, status_code=status.HTTP_201_CREATED)
async def debts_create(
    data: DebtCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await create_debt(session, ctx.workspace.id, ctx.user_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    try:
        payment = await add_payment(session, ctx.workspace.id, ctx.user_id, debt_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not payment:
        raise HTTPException(status_code=404, detail="Debt not found")
    balance = payment.debt.outstanding_balance if payment.debt is not None else None
    return {"id": payment.id, "outstanding_balance": str(balance) if balance is not None else None}


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
    """Price simulation. POST because the extras belong in a body; writes nothing."""
    try:
        return await simulate_amortize(session, ctx.workspace.id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/renegotiation/pmt-hint")
async def renegotiation_pmt_hint(
    data: PmtHintBody,
    ctx: WorkspaceContext = Depends(current_workspace),
):
    """Theoretical PMT. POST because CET and term belong in a body; writes nothing."""
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
