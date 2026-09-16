"""Additive restore of a workspace backup zip.

The archive is the same JSON zip `backup_service` produces. Restore never
overwrites an existing row, never posts import candidates to the ledger, and
never writes original file bytes (those come back with the instance dump).
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from typing import cast

import pyzipper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.debt import Debt, DebtCashPlan, DebtInstallment, DebtOffer, DebtPayment
from app.services import audit_service


def _open_archive(data: bytes, password: str | None) -> zipfile.ZipFile:
    buf = io.BytesIO(data)
    if password:
        archive = pyzipper.AESZipFile(buf)
        archive.setpassword(password.encode("utf-8"))
        return cast(zipfile.ZipFile, archive)
    return zipfile.ZipFile(buf)


def _load_json(archive: zipfile.ZipFile, name: str) -> list[dict]:
    if name not in archive.namelist():
        return []
    payload = json.loads(archive.read(name).decode("utf-8"))
    return payload if isinstance(payload, list) else []


def _parse_date(value: str | None):
    if not value:
        return None
    return date.fromisoformat(value[:10])


async def restore_workspace_archive(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: bytes,
    password: str | None = None,
) -> dict[str, int]:
    try:
        archive = _open_archive(data, password)
    except RuntimeError as exc:
        raise ValueError("Could not open the archive. Check the password.") from exc

    with archive:
        debts = _load_json(archive, "debts.json")
        installments = _load_json(archive, "debt_installments.json")
        payments = _load_json(archive, "debt_payments.json")
        cash_plans = _load_json(archive, "debt_cash_plans.json")
        offers = _load_json(archive, "debt_offers.json")

    restored = {
        "debts": 0,
        "debt_installments": 0,
        "debt_payments": 0,
        "debt_cash_plans": 0,
        "debt_offers": 0,
    }

    for row in debts:
        debt_id = uuid.UUID(str(row["id"]))
        if await session.get(Debt, debt_id):
            continue
        session.add(
            Debt(
                id=debt_id,
                user_id=user_id,
                workspace_id=workspace_id,
                account_id=uuid.UUID(row["account_id"]) if row.get("account_id") else None,
                name=row["name"],
                creditor=row["creditor"],
                currency=row.get("currency") or "USD",
                principal=Decimal(str(row["principal"])),
                outstanding_balance=Decimal(str(row["outstanding_balance"])),
                interest_rate=Decimal(str(row["interest_rate"])) if row.get("interest_rate") is not None else None,
                indexer=row.get("indexer"),
                origination_date=_parse_date(row.get("origination_date")),
                maturity_date=_parse_date(row.get("maturity_date")),
                collateral=row.get("collateral"),
                product=row.get("product") or "outro",
                delinquency_status=row.get("delinquency_status") or "em_dia",
                days_past_due=int(row.get("days_past_due") or 0),
                penalty_amount=Decimal(str(row["penalty_amount"])) if row.get("penalty_amount") is not None else Decimal("0"),
                installment_amount=Decimal(str(row["installment_amount"])) if row.get("installment_amount") is not None else None,
                remaining_term_months=int(row["remaining_term_months"]) if row.get("remaining_term_months") is not None else None,
                cet_annual_informed=Decimal(str(row["cet_annual_informed"])) if row.get("cet_annual_informed") is not None else None,
                due_date=_parse_date(row.get("due_date")),
                guarantee=row.get("guarantee") or "nenhuma",
                estimated_cost=Decimal(str(row["estimated_cost"])) if row.get("estimated_cost") is not None else None,
                payoff_strategy=row.get("payoff_strategy"),
                strategy_assumptions=row.get("strategy_assumptions"),
                notes=row.get("notes"),
                status=row.get("status") or "active",
                source=row.get("source") or "restore",
                review_status=row.get("review_status") or "confirmed",
            )
        )
        restored["debts"] += 1

    await session.flush()

    for row in installments:
        row_id = uuid.UUID(str(row["id"]))
        if await session.get(DebtInstallment, row_id):
            continue
        debt = await session.get(Debt, uuid.UUID(str(row["debt_id"])))
        if not debt or debt.workspace_id != workspace_id:
            continue
        session.add(
            DebtInstallment(
                id=row_id,
                debt_id=debt.id,
                workspace_id=workspace_id,
                number=int(row["number"]),
                due_date=_parse_date(row["due_date"]),
                amount=Decimal(str(row["amount"])),
                principal_amount=Decimal(str(row["principal_amount"])) if row.get("principal_amount") is not None else None,
                interest_amount=Decimal(str(row["interest_amount"])) if row.get("interest_amount") is not None else None,
                currency=row.get("currency") or "USD",
                status=row.get("status") or "pending",
            )
        )
        restored["debt_installments"] += 1

    for row in payments:
        row_id = uuid.UUID(str(row["id"]))
        if await session.get(DebtPayment, row_id):
            continue
        debt = await session.get(Debt, uuid.UUID(str(row["debt_id"])))
        if not debt or debt.workspace_id != workspace_id:
            continue
        session.add(
            DebtPayment(
                id=row_id,
                debt_id=debt.id,
                workspace_id=workspace_id,
                paid_on=_parse_date(row["paid_on"]),
                amount=Decimal(str(row["amount"])),
                currency=row.get("currency") or "USD",
                principal_amount=Decimal(str(row["principal_amount"])) if row.get("principal_amount") is not None else None,
                interest_amount=Decimal(str(row["interest_amount"])) if row.get("interest_amount") is not None else None,
                notes=row.get("notes"),
            )
        )
        restored["debt_payments"] += 1

    for row in cash_plans:
        row_id = uuid.UUID(str(row["id"]))
        if await session.get(DebtCashPlan, row_id):
            continue
        existing_plan = await session.scalar(
            select(DebtCashPlan).where(DebtCashPlan.workspace_id == workspace_id)
        )
        if existing_plan:
            continue
        session.add(
            DebtCashPlan(
                id=row_id,
                user_id=user_id,
                workspace_id=workspace_id,
                income=Decimal(str(row.get("income") or 0)),
                variable_income=Decimal(str(row.get("variable_income") or 0)),
                essential=Decimal(str(row.get("essential") or 0)),
                discretionary=Decimal(str(row.get("discretionary") or 0)),
                reserve=Decimal(str(row.get("reserve") or 0)),
                shock=Decimal(str(row.get("shock") or 0)),
                steps=row.get("steps") or {},
            )
        )
        restored["debt_cash_plans"] += 1

    for row in offers:
        row_id = uuid.UUID(str(row["id"]))
        if await session.get(DebtOffer, row_id):
            continue
        debt = await session.get(Debt, uuid.UUID(str(row["debt_id"])))
        if not debt or debt.workspace_id != workspace_id:
            continue
        session.add(
            DebtOffer(
                id=row_id,
                debt_id=debt.id,
                workspace_id=workspace_id,
                path=row.get("path") or "outro",
                name=row["name"],
                payoff=Decimal(str(row["payoff"])),
                cet_monthly=Decimal(str(row["cet_monthly"])) if row.get("cet_monthly") is not None else None,
                installment=Decimal(str(row["installment"])),
                term_months=int(row["term_months"]) if row.get("term_months") is not None else None,
                down_payment=Decimal(str(row.get("down_payment") or 0)),
                waiver=Decimal(str(row.get("waiver") or 0)),
                grace=row.get("grace") or "nao",
                new_guarantee=bool(row.get("new_guarantee")),
                operational_notes=row.get("operational_notes"),
            )
        )
        restored["debt_offers"] += 1

    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="backup.restore",
        entity_type="workspace",
        entity_id=str(workspace_id),
        summary="Restored debts from a workspace archive without posting ledger rows",
        extra=restored,
    )
    await session.commit()
    return restored
