from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace, current_writable_workspace
from app.models.account import Account
from app.models.asset import Asset
from app.models.asset_value import AssetValue
from app.models.audit import AuditEvent
from app.models.budget import Budget
from app.models.category import Category
from app.models.category_group import CategoryGroup
from app.models.debt import Debt, DebtCashPlan, DebtInstallment, DebtOffer, DebtPayment
from app.models.import_log import ImportLog
from app.models.processing_job import ProcessingJob
from app.models.recurring_transaction import RecurringTransaction
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.models.vault import ImportCandidate, StoredObject, VaultDocument
from app.schemas.export import BackupRequest
from app.services.backup_service import build_backup_archive
from app.services.restore_service import restore_workspace_archive

router = APIRouter(prefix="/api/export", tags=["export"])


def _serialize(obj) -> dict:
    """Convert a SQLAlchemy model instance to a JSON-serializable dict."""
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.key)
        if isinstance(val, UUID):
            val = str(val)
        elif isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = str(val)
        d[col.key] = val
    return d


async def _collect(ctx: WorkspaceContext, session: AsyncSession) -> dict[str, object]:
    """Every entity in the workspace, keyed by the file it becomes."""
    ws_id = ctx.workspace.id

    accounts = (await session.execute(select(Account).where(Account.workspace_id == ws_id))).scalars().all()
    transactions = (await session.execute(select(Transaction).where(Transaction.workspace_id == ws_id))).scalars().all()
    categories = (await session.execute(select(Category).where(Category.workspace_id == ws_id))).scalars().all()
    category_groups = (await session.execute(select(CategoryGroup).where(CategoryGroup.workspace_id == ws_id))).scalars().all()
    rules = (await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all()
    recurring_transactions = (await session.execute(select(RecurringTransaction).where(RecurringTransaction.workspace_id == ws_id))).scalars().all()
    budgets = (await session.execute(select(Budget).where(Budget.workspace_id == ws_id))).scalars().all()
    assets = (await session.execute(select(Asset).where(Asset.workspace_id == ws_id))).scalars().all()
    import_logs = (await session.execute(select(ImportLog).where(ImportLog.workspace_id == ws_id))).scalars().all()
    debts = (await session.execute(select(Debt).where(Debt.workspace_id == ws_id))).scalars().all()
    debt_installments = (await session.execute(select(DebtInstallment).where(DebtInstallment.workspace_id == ws_id))).scalars().all()
    debt_payments = (await session.execute(select(DebtPayment).where(DebtPayment.workspace_id == ws_id))).scalars().all()
    debt_cash_plans = (await session.execute(select(DebtCashPlan).where(DebtCashPlan.workspace_id == ws_id))).scalars().all()
    debt_offers = (await session.execute(select(DebtOffer).where(DebtOffer.workspace_id == ws_id))).scalars().all()
    vault_documents = (await session.execute(select(VaultDocument).where(VaultDocument.workspace_id == ws_id))).scalars().all()
    stored_objects = (await session.execute(select(StoredObject).where(StoredObject.workspace_id == ws_id))).scalars().all()
    import_candidates = (await session.execute(select(ImportCandidate).where(ImportCandidate.workspace_id == ws_id))).scalars().all()
    processing_jobs = (await session.execute(select(ProcessingJob).where(ProcessingJob.workspace_id == ws_id))).scalars().all()
    audit_events = (await session.execute(select(AuditEvent).where(AuditEvent.workspace_id == ws_id))).scalars().all()

    asset_ids = [a.id for a in assets]
    if asset_ids:
        asset_values = (await session.execute(select(AssetValue).where(AssetValue.asset_id.in_(asset_ids)))).scalars().all()
    else:
        asset_values = []

    entities = {
        "accounts": accounts,
        "transactions": transactions,
        "categories": categories,
        "category_groups": category_groups,
        "rules": rules,
        "recurring_transactions": recurring_transactions,
        "budgets": budgets,
        "assets": assets,
        "asset_values": asset_values,
        "import_logs": import_logs,
        "debts": debts,
        "debt_installments": debt_installments,
        "debt_payments": debt_payments,
        "debt_cash_plans": debt_cash_plans,
        "debt_offers": debt_offers,
        "vault_documents": vault_documents,
        "stored_objects": stored_objects,
        "import_candidates": import_candidates,
        "processing_jobs": processing_jobs,
        "audit_events": audit_events,
    }

    files: dict[str, object] = {}
    entity_counts = {}
    for name, rows in entities.items():
        serialized = [_serialize(r) for r in rows]
        entity_counts[name] = len(serialized)
        files[f"{name}.json"] = serialized

    files["metadata.json"] = {
        "export_date": datetime.now(timezone.utc).isoformat(),
        "format_version": "1.1",
        "workspace_id": str(ws_id),
        "workspace_name": ctx.workspace.name,
        "entity_counts": entity_counts,
        "includes_original_files": False,
    }
    return files


def _as_download(archive: bytes) -> StreamingResponse:
    today = date.today().isoformat()
    return StreamingResponse(
        iter([archive]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="securo-backup-{today}.zip"'},
    )


@router.get("/backup")
async def backup(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Export every entity in the current workspace as a JSON zip.

    Backup is scoped to one workspace at a time — users with multiple
    workspaces back each one up separately. AssetValue inherits its
    workspace from its Asset and is filtered transitively.
    """
    return _as_download(build_backup_archive(await _collect(ctx, session)))


@router.post("/backup")
async def backup_protected(
    body: BackupRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """The same archive, encrypted with AES-256 when a password is given.

    A POST because the password belongs in a body: a query string is written
    to browser history, proxy logs and server access logs. Securo never stores
    the password and cannot recover the archive without it.
    """
    password = body.password.get_secret_value() if body.password else None
    return _as_download(build_backup_archive(await _collect(ctx, session), password))


@router.post("/restore")
async def restore(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Additive restore of debts from a workspace backup zip.

    Existing rows are left untouched. Import candidates are never posted.
    Original document bytes are not in the zip; restore those with the
    instance backup scripts.
    """
    max_bytes = get_settings().storage_max_document_size_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Backup is too large")
    try:
        restored = await restore_workspace_archive(
            session,
            workspace_id=ctx.workspace.id,
            user_id=ctx.user_id,
            data=data,
            password=password or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return restored
