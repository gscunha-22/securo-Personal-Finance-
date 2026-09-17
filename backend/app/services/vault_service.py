import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.core.config import get_settings
from app.models.account import Account
from app.models.processing_job import ProcessingJob
from app.models.transaction import Transaction
from app.models.vault import (
    DocumentConflict,
    DocumentExtraction,
    DocumentVersion,
    ExtractedField,
    HumanDecision,
    ImportCandidate,
    StoredObject,
    VaultDocument,
)
from app.providers import get_storage_provider
from app.services import audit_service, job_service
from app.services.extraction import (
    classify_document,
    detect_mime,
    extract_structured_rows,
    fingerprint,
    ocr_image,
    parse_integrity,
    sha256_hex,
    suggest_recurrence,
)
from app.services.fx_rate_service import stamp_primary_amount

ALLOWED_MIMES = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/x-ofx",
    "application/x-qif",
    "application/xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
    "image/gif",
    "application/zip",
}

IMAGE_MIMES = {"image/png", "image/jpeg", "image/gif"}

# Columns DocumentRead returns. storage_key stays off list/detail so a
# document listing never ships the vault path.
_STORED_OBJECT_READ_COLUMNS = (
    StoredObject.original_filename,
    StoredObject.detected_mime,
    StoredObject.sha256,
    StoredObject.byte_size,
)


def _scan_bytes(data: bytes) -> str:
    """Equivalent of antivirus when ClamAV is not in the image: reject obvious payloads."""
    if b"<script" in data[:8000].lower() or b"<?php" in data[:8000].lower():
        return "rejected"
    return "clean_magic"


async def upload_document(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    declared_mime: str,
    data: bytes,
    account_id: uuid.UUID | None = None,
    origin: str = "upload",
    correlation_id: str | None = None,
    source_connection_id: uuid.UUID | None = None,
) -> VaultDocument:
    settings = get_settings()
    max_bytes = settings.storage_max_document_size_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ValueError(f"File exceeds the {settings.storage_max_document_size_mb} MB limit")
    if not data:
        raise ValueError("Empty file")
    if account_id is not None:
        account = await session.scalar(
            select(Account).where(Account.id == account_id, Account.workspace_id == workspace_id)
        )
        if account is None:
            raise ValueError("Account not found in this workspace")

    detected = detect_mime(data, filename, declared_mime)
    if detected not in ALLOWED_MIMES:
        raise ValueError("This file type is not accepted")
    scan = _scan_bytes(data)
    if scan == "rejected":
        raise ValueError("File failed safety checks")

    digest = sha256_hex(data)
    existing_object = await session.scalar(
        select(StoredObject).where(
            StoredObject.workspace_id == workspace_id,
            StoredObject.sha256 == digest,
        )
    )
    if existing_object:
        existing_doc = await session.scalar(
            select(VaultDocument).where(
                VaultDocument.workspace_id == workspace_id,
                VaultDocument.stored_object_id == existing_object.id,
            )
        )
        if existing_doc:
            return existing_doc

    storage = get_storage_provider()
    storage_key = f"{workspace_id}/vault/{digest}"
    await storage.upload(storage_key, data, detected)
    stored = existing_object or StoredObject(
        workspace_id=workspace_id,
        sha256=digest,
        storage_key=storage_key,
        byte_size=len(data),
        declared_mime=declared_mime or "application/octet-stream",
        detected_mime=detected,
        original_filename=filename,
        scan_status=scan,
    )
    if existing_object is None:
        session.add(stored)
        await session.flush()

    document = VaultDocument(
        user_id=user_id,
        workspace_id=workspace_id,
        stored_object_id=stored.id,
        account_id=account_id,
        source_connection_id=source_connection_id,
        document_type="unknown",
        status="uploaded",
        origin=origin,
    )
    session.add(document)
    await session.flush()
    job = await job_service.enqueue(
        session,
        workspace_id=workspace_id,
        job_type="extract_document",
        idempotency_key=fingerprint(str(workspace_id), "extract", digest),
        payload={"document_id": str(document.id)},
        correlation_id=correlation_id,
    )
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="document.upload",
        entity_type="vault_document",
        entity_id=document.id,
        summary=f"Uploaded {filename}",
        extra={"sha256": digest, "mime": detected},
    )
    await session.commit()
    from app.services import job_dispatch

    await job_dispatch.dispatch_or_run(session, job)
    loaded = await get_document(session, workspace_id, document.id)
    return loaded or document


async def process_extraction_job(session: AsyncSession, job_id: uuid.UUID) -> ProcessingJob:
    job = await session.scalar(
        select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
    )
    if job is None:
        raise LookupError("Job not found")
    if job.status in {"completed", "waiting_review", "partially_completed", "cancelled"}:
        return job
    now = datetime.now(timezone.utc)
    if (
        job.status == "running"
        and job.lock_expires_at is not None
        and job.lock_expires_at > now
    ):
        return job
    await job_service.mark_running(session, job)
    await session.commit()
    try:
        document_id = uuid.UUID(job.payload["document_id"])
        await extract_document(session, document_id)
        job = await session.get(ProcessingJob, job_id)
        if job is None:
            raise LookupError("Job not found")
        await job_service.finish(session, job, "waiting_review")
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


async def extract_document(session: AsyncSession, document_id: uuid.UUID) -> VaultDocument:
    document = await session.scalar(
        select(VaultDocument)
        .where(VaultDocument.id == document_id)
        .options(selectinload(VaultDocument.stored_object))
    )
    if not document:
        raise LookupError("Document not found")
    storage = get_storage_provider()
    data = await storage.download(document.stored_object.storage_key)
    mime = document.stored_object.detected_mime
    filename = document.stored_object.original_filename

    rows: list[dict] = []
    method = "unsupported"
    raw_text = ""
    if mime in IMAGE_MIMES:
        raw_text, method = ocr_image(data)
        if not raw_text:
            document.status = "needs_ocr"
            document.document_type = "receipt"
            extraction = await _add_extraction(
                session,
                document,
                method=method or "pending_ocr",
                status="waiting_review",
                doc_type="receipt",
                raw_text=None,
            )
            await _add_version(
                session,
                document,
                extraction,
                interpreter="ocr",
                status="waiting_review",
                integrity={"status": "not_applicable", "printed_total": None, "computed_total": Decimal("0.00")},
            )
            return document
        rows = _rows_from_ocr_text(raw_text)
    elif mime == "application/pdf":
        rows, method, raw_text = extract_structured_rows(data, mime, filename)
        if not (raw_text or "").strip() and not rows:
            document.status = "needs_ocr"
            extraction = await _add_extraction(
                session,
                document,
                method="pending_ocr",
                status="waiting_review",
                doc_type="unknown",
                raw_text=None,
            )
            await _add_version(
                session,
                document,
                extraction,
                interpreter="ocr",
                status="waiting_review",
                integrity={"status": "not_applicable", "printed_total": None, "computed_total": Decimal("0.00")},
            )
            return document
    else:
        rows, method, raw_text = extract_structured_rows(data, mime, filename)

    doc_type = classify_document(filename, mime, raw_text)
    document.document_type = doc_type
    extraction = await _add_extraction(
        session,
        document,
        method=method,
        status="completed",
        doc_type=doc_type,
        raw_text=raw_text[:20000] if raw_text else None,
    )
    session.add(
        ExtractedField(
            extraction_id=extraction.id,
            name="document_type",
            value=doc_type,
            locator="classifier",
            method=method,
            confidence=Decimal("0.8000") if doc_type != "unknown" else Decimal("0.2000"),
        )
    )
    integrity = parse_integrity(rows, raw_text)
    version = await _add_version(
        session,
        document,
        extraction,
        interpreter="ocr" if method.startswith("ocr") else "deterministic",
        status="completed",
        integrity=integrity,
    )
    if integrity["status"] == "conflict":
        session.add(
            DocumentConflict(
                document_id=document.id,
                workspace_id=document.workspace_id,
                version_id=version.id,
                kind="parse_integrity",
                summary=(
                    f"Printed total {integrity['printed_total']} does not match "
                    f"sum of parts {integrity['computed_total']}"
                ),
            )
        )
    recurrence = suggest_recurrence(rows)
    duplicates = await _find_duplicates(session, document.workspace_id, document.account_id, rows)
    for row in rows:
        key = fingerprint(
            str(document.workspace_id),
            document.stored_object.sha256,
            str(row["competence_date"]),
            str(row["amount"]),
            row["txn_type"],
            row["description"],
            row.get("external_id") or "",
            row.get("locator") or "",
        )
        existing = await session.scalar(
            select(ImportCandidate).where(
                ImportCandidate.workspace_id == document.workspace_id,
                ImportCandidate.idempotency_key == key,
            )
        )
        if existing:
            continue
        suggestion = suggest_category(row["description"], row.get("payee"))
        extra = {}
        if recurrence:
            extra["recurrence_suggestion"] = recurrence
            suggestion["rationale"] = (
                f"{suggestion['rationale']} Recurrence inferred, not confirmed."
            )
        candidate = ImportCandidate(
            workspace_id=document.workspace_id,
            document_id=document.id,
            extraction_id=extraction.id,
            account_id=document.account_id,
            selected=False,
            status="pending",
            description=row["description"][:500],
            amount=row["amount"],
            currency=row["currency"] or "USD",
            competence_date=row["competence_date"],
            payment_date=row.get("payment_date"),
            txn_type=row["txn_type"],
            payee=row.get("payee"),
            external_id=row.get("external_id"),
            locator=row.get("locator"),
            confidence=row.get("confidence") or Decimal("1.0000"),
            duplicate_of_transaction_id=duplicates.get(
                (row["competence_date"], row["amount"], row["currency"] or "USD")
            ),
            suggested_category=suggestion["label"],
            suggestion_rationale=suggestion["rationale"],
            suggestion_confidence=suggestion["confidence"],
            idempotency_key=key,
            extra=extra or None,
        )
        session.add(candidate)
        session.add(
            ExtractedField(
                extraction_id=extraction.id,
                name="transaction",
                value=f"{row['competence_date']}|{row['amount']}|{row['description'][:80]}",
                locator=row.get("locator"),
                method=method,
                confidence=row.get("confidence") or Decimal("1.0000"),
            )
        )
    document.status = "waiting_review"
    return document


async def _add_extraction(
    session: AsyncSession,
    document: VaultDocument,
    *,
    method: str,
    status: str,
    doc_type: str,
    raw_text: str | None,
) -> DocumentExtraction:
    extraction = DocumentExtraction(
        document_id=document.id,
        workspace_id=document.workspace_id,
        method=method,
        status=status,
        document_type_guess=doc_type,
        raw_text=raw_text,
    )
    session.add(extraction)
    await session.flush()
    return extraction


async def _add_version(
    session: AsyncSession,
    document: VaultDocument,
    extraction: DocumentExtraction,
    *,
    interpreter: str,
    status: str,
    integrity: dict,
) -> DocumentVersion:
    current = await session.scalar(
        select(func.max(DocumentVersion.version_number)).where(DocumentVersion.document_id == document.id)
    )
    version = DocumentVersion(
        document_id=document.id,
        workspace_id=document.workspace_id,
        extraction_id=extraction.id,
        version_number=int(current or 0) + 1,
        interpreter=interpreter,
        status=status,
        parse_integrity=integrity["status"],
        printed_total=integrity.get("printed_total"),
        computed_total=integrity.get("computed_total"),
    )
    session.add(version)
    await session.flush()
    return version


def _rows_from_ocr_text(text: str) -> list[dict]:
    from app.services.extraction import _rows_from_pdf_text

    return _rows_from_pdf_text(text)


def suggest_category(description: str, payee: Optional[str]) -> dict:
    """Deterministic suggestions only. Never invents amounts or dates."""
    blob = f"{description} {payee or ''}".lower()
    rules = [
        ("grocery", ("supermarket", "grocery", "mercado", "ifood")),
        ("utilities", ("energia", "light", "enel", "internet", "vivo", "claro")),
        ("transport", ("uber", "99", "metro", "fuel", "posto")),
        ("housing", ("aluguel", "rent", "condominio")),
        ("income", ("salary", "salario", "payroll", "pix received")),
    ]
    for label, needles in rules:
        if any(n in blob for n in needles):
            return {
                "label": label,
                "rationale": f"Matched a known {label} keyword in the description.",
                "confidence": Decimal("0.7000"),
            }
    return {
        "label": None,
        "rationale": "No deterministic category rule matched.",
        "confidence": Decimal("0.0000"),
    }


async def _find_duplicates(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    account_id: uuid.UUID | None,
    rows: list[dict],
) -> dict[tuple, uuid.UUID]:
    if not rows:
        return {}
    dates = {row["competence_date"] for row in rows}
    query = select(
        Transaction.id, Transaction.date, Transaction.amount, Transaction.currency
    ).where(
        Transaction.workspace_id == workspace_id,
        Transaction.date.in_(dates),
    )
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    existing = (await session.execute(query)).all()
    index: dict[tuple, uuid.UUID] = {}
    for txn_id, txn_date, amount, currency in existing:
        index[(txn_date, abs(amount), currency)] = txn_id
    found: dict[tuple, uuid.UUID] = {}
    for row in rows:
        key = (row["competence_date"], row["amount"], row["currency"] or "USD")
        if key in index:
            found[key] = index[key]
    return found


async def latest_interpretation_versions(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(DocumentVersion.document_id, func.max(DocumentVersion.version_number))
        .where(DocumentVersion.document_id.in_(document_ids))
        .group_by(DocumentVersion.document_id)
    )
    return {document_id: version_number for document_id, version_number in rows.all()}


async def list_documents(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[VaultDocument]:
    result = await session.execute(
        select(VaultDocument)
        .where(VaultDocument.workspace_id == workspace_id)
        .options(
            selectinload(VaultDocument.stored_object).load_only(*_STORED_OBJECT_READ_COLUMNS)
        )
        .order_by(VaultDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_document(
    session: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> Optional[VaultDocument]:
    return await session.scalar(
        select(VaultDocument)
        .where(VaultDocument.id == document_id, VaultDocument.workspace_id == workspace_id)
        .options(
            selectinload(VaultDocument.stored_object).load_only(*_STORED_OBJECT_READ_COLUMNS)
        )
    )


async def list_extracted_fields(
    session: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> Optional[list[ExtractedField]]:
    exists = await session.scalar(
        select(VaultDocument.id).where(
            VaultDocument.id == document_id, VaultDocument.workspace_id == workspace_id
        )
    )
    if exists is None:
        return None
    result = await session.execute(
        select(ExtractedField)
        .join(DocumentExtraction, ExtractedField.extraction_id == DocumentExtraction.id)
        .where(DocumentExtraction.document_id == document_id)
        .options(
            load_only(
                ExtractedField.name,
                ExtractedField.value,
                ExtractedField.locator,
                ExtractedField.method,
                ExtractedField.confidence,
                ExtractedField.human_correction,
            )
        )
        .order_by(DocumentExtraction.created_at, ExtractedField.created_at)
    )
    return list(result.scalars().all())


async def download_original(
    session: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[StoredObject, bytes]:
    stored = await session.scalar(
        select(StoredObject)
        .join(VaultDocument, VaultDocument.stored_object_id == StoredObject.id)
        .where(VaultDocument.id == document_id, VaultDocument.workspace_id == workspace_id)
        .options(
            load_only(
                StoredObject.storage_key,
                StoredObject.original_filename,
                StoredObject.detected_mime,
                StoredObject.sha256,
                StoredObject.byte_size,
            )
        )
    )
    if stored is None:
        raise LookupError("Document not found")
    data = await get_storage_provider().download(stored.storage_key)
    return stored, data


async def list_candidates(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    status: str | None = None,
    *,
    limit: int = 500,
    offset: int = 0,
) -> list[ImportCandidate]:
    query = (
        select(ImportCandidate)
        .where(ImportCandidate.workspace_id == workspace_id)
        .options(
            load_only(
                ImportCandidate.document_id,
                ImportCandidate.selected,
                ImportCandidate.status,
                ImportCandidate.description,
                ImportCandidate.amount,
                ImportCandidate.currency,
                ImportCandidate.competence_date,
                ImportCandidate.payment_date,
                ImportCandidate.txn_type,
                ImportCandidate.payee,
                ImportCandidate.locator,
                ImportCandidate.confidence,
                ImportCandidate.duplicate_of_transaction_id,
                ImportCandidate.suggested_category,
                ImportCandidate.suggestion_rationale,
                ImportCandidate.suggestion_confidence,
                ImportCandidate.posted_transaction_id,
            )
        )
    )
    if status:
        query = query.where(ImportCandidate.status == status)
    query = query.order_by(ImportCandidate.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(query)).scalars().all())


async def decide_candidates(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
    decision: str,
    account_id: uuid.UUID | None = None,
) -> dict:
    if decision not in {"approve", "reject", "defer"}:
        raise ValueError("Decision must be approve, reject, or defer")
    result = await session.execute(
        select(ImportCandidate)
        .where(
            ImportCandidate.workspace_id == workspace_id,
            ImportCandidate.id.in_(candidate_ids),
        )
        .with_for_update()
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return {"updated": 0, "posted": 0}
    posted = 0
    for candidate in candidates:
        if decision == "defer":
            candidate.status = "deferred"
            candidate.selected = False
            session.add(
                HumanDecision(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    candidate_id=candidate.id,
                    document_id=candidate.document_id,
                    decision="defer",
                )
            )
            continue
        if decision == "reject":
            candidate.status = "rejected"
            candidate.selected = False
            candidate.decided_by = user_id
            from datetime import datetime, timezone

            candidate.decided_at = datetime.now(timezone.utc)
            session.add(
                HumanDecision(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    candidate_id=candidate.id,
                    document_id=candidate.document_id,
                    decision="reject",
                )
            )
            continue
        account = candidate.account_id or account_id
        if not account:
            raise ValueError("An account is required before approving candidates")
        if candidate.posted_transaction_id:
            posted += 1
            session.add(
                HumanDecision(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    candidate_id=candidate.id,
                    document_id=candidate.document_id,
                    decision="approve",
                )
            )
            continue
        txn = await _post_candidate(session, candidate, account, user_id, workspace_id)
        candidate.posted_transaction_id = txn.id
        candidate.status = "imported"
        candidate.selected = True
        candidate.decided_by = user_id
        from datetime import datetime, timezone

        candidate.decided_at = datetime.now(timezone.utc)
        posted += 1
        session.add(
            HumanDecision(
                workspace_id=workspace_id,
                user_id=user_id,
                candidate_id=candidate.id,
                document_id=candidate.document_id,
                decision="approve",
            )
        )
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action=f"import.{decision}",
        entity_type="import_candidate",
        entity_id=candidates[0].document_id,
        summary=f"{decision} {len(candidates)} candidates",
        extra={"count": len(candidates), "posted": posted},
    )
    await session.commit()
    return {"updated": len(candidates), "posted": posted}


async def _post_candidate(
    session: AsyncSession,
    candidate: ImportCandidate,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Transaction:
    account = await session.scalar(
        select(Account).where(Account.id == account_id, Account.workspace_id == workspace_id)
    )
    if not account:
        raise ValueError("Account not found")
    if candidate.duplicate_of_transaction_id:
        existing = await session.get(Transaction, candidate.duplicate_of_transaction_id)
        if existing:
            return existing
    txn = Transaction(
        user_id=user_id,
        workspace_id=workspace_id,
        account_id=account_id,
        description=candidate.description,
        amount=candidate.amount,
        currency=candidate.currency,
        date=candidate.competence_date,
        effective_date=candidate.payment_date or candidate.competence_date,
        type=candidate.txn_type,
        source="document",
        status="posted",
        payee=candidate.payee,
        external_id=candidate.external_id,
        category_id=candidate.category_id,
    )
    session.add(txn)
    await session.flush()
    await stamp_primary_amount(session, user_id, txn)
    return txn


async def revert_import(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(ImportCandidate).where(
            ImportCandidate.workspace_id == workspace_id,
            ImportCandidate.document_id == document_id,
            ImportCandidate.status == "imported",
        )
    )
    reverted = 0
    for candidate in result.scalars():
        if candidate.posted_transaction_id:
            txn = await session.get(Transaction, candidate.posted_transaction_id)
            if txn and txn.workspace_id == workspace_id:
                await session.delete(txn)
        candidate.status = "reverted"
        candidate.posted_transaction_id = None
        reverted += 1
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="import.revert",
        entity_type="vault_document",
        entity_id=document_id,
        summary=f"Reverted {reverted} imported rows without deleting the audit trail",
    )
    await session.commit()
    return reverted


def ai_validate_suggestion(payload: dict) -> dict:
    """Reject model output that tries to invent facts."""
    forbidden = {"amount", "date", "balance", "currency", "competence_date", "payment_date"}
    if any(k in payload for k in forbidden):
        raise ValueError("AI output may not include financial facts")
    allowed = {"category", "payee", "description", "rationale", "confidence", "recurrence"}
    cleaned = {k: v for k, v in payload.items() if k in allowed}
    confidence = cleaned.get("confidence")
    if confidence is not None:
        try:
            value = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid confidence") from exc
        if not 0 <= value <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        cleaned["confidence"] = value
    if "rationale" not in cleaned:
        raise ValueError("AI suggestions require a rationale")
    return cleaned
