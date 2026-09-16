import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.debt import Debt, DebtInstallment, DebtPayment
from app.services import audit_service


class DebtCreate(BaseModel):
    name: str
    creditor: str
    currency: str = "USD"
    principal: Decimal
    outstanding_balance: Decimal
    interest_rate: Optional[Decimal] = None
    indexer: Optional[str] = None
    origination_date: Optional[date] = None
    maturity_date: Optional[date] = None
    collateral: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    payoff_strategy: Optional[str] = None
    strategy_assumptions: Optional[str] = None
    notes: Optional[str] = None
    account_id: Optional[uuid.UUID] = None


class DebtUpdate(BaseModel):
    name: Optional[str] = None
    creditor: Optional[str] = None
    outstanding_balance: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    indexer: Optional[str] = None
    maturity_date: Optional[date] = None
    collateral: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    payoff_strategy: Optional[str] = None
    strategy_assumptions: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class DebtPaymentCreate(BaseModel):
    paid_on: date
    amount: Decimal
    currency: str = "USD"
    principal_amount: Optional[Decimal] = None
    interest_amount: Optional[Decimal] = None
    notes: Optional[str] = None


class DebtInstallmentCreate(BaseModel):
    number: int = Field(ge=1)
    due_date: date
    amount: Decimal
    currency: str = "USD"
    principal_amount: Optional[Decimal] = None
    interest_amount: Optional[Decimal] = None


class DebtRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    creditor: str
    currency: str
    principal: Decimal
    outstanding_balance: Decimal
    interest_rate: Optional[Decimal]
    indexer: Optional[str]
    origination_date: Optional[date]
    maturity_date: Optional[date]
    collateral: Optional[str]
    estimated_cost: Optional[Decimal]
    payoff_strategy: Optional[str]
    strategy_assumptions: Optional[str]
    notes: Optional[str]
    status: str
    source: str
    review_status: str


async def list_debts(session: AsyncSession, workspace_id: uuid.UUID) -> list[Debt]:
    result = await session.execute(
        select(Debt)
        .where(Debt.workspace_id == workspace_id)
        .options(selectinload(Debt.installments), selectinload(Debt.payments))
        .order_by(Debt.created_at.desc())
    )
    return list(result.scalars().all())


async def create_debt(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: DebtCreate,
) -> Debt:
    debt = Debt(
        user_id=user_id,
        workspace_id=workspace_id,
        account_id=data.account_id,
        name=data.name,
        creditor=data.creditor,
        currency=data.currency,
        principal=data.principal,
        outstanding_balance=data.outstanding_balance,
        interest_rate=data.interest_rate,
        indexer=data.indexer,
        origination_date=data.origination_date,
        maturity_date=data.maturity_date,
        collateral=data.collateral,
        estimated_cost=data.estimated_cost,
        payoff_strategy=data.payoff_strategy,
        strategy_assumptions=data.strategy_assumptions,
        notes=data.notes,
        status="active",
        source="manual",
        review_status="confirmed",
    )
    session.add(debt)
    await session.flush()
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.create",
        entity_type="debt",
        entity_id=debt.id,
        summary=f"Created debt {debt.name}",
    )
    await session.commit()
    await session.refresh(debt)
    return debt


async def update_debt(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    debt_id: uuid.UUID,
    data: DebtUpdate,
) -> Optional[Debt]:
    debt = await session.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(debt, field, value)
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.update",
        entity_type="debt",
        entity_id=debt.id,
        summary=f"Updated debt {debt.name}",
    )
    await session.commit()
    await session.refresh(debt)
    return debt


async def add_payment(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    debt_id: uuid.UUID,
    data: DebtPaymentCreate,
) -> Optional[DebtPayment]:
    debt = await session.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        return None
    payment = DebtPayment(
        debt_id=debt.id,
        workspace_id=workspace_id,
        paid_on=data.paid_on,
        amount=data.amount,
        currency=data.currency,
        principal_amount=data.principal_amount,
        interest_amount=data.interest_amount,
        notes=data.notes,
    )
    debt.outstanding_balance = max(Decimal("0.00"), debt.outstanding_balance - data.amount)
    session.add(payment)
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.payment",
        entity_type="debt",
        entity_id=debt.id,
        summary=f"Recorded payment of {data.amount} {data.currency}",
    )
    await session.commit()
    await session.refresh(payment)
    return payment


async def add_installment(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    debt_id: uuid.UUID,
    data: DebtInstallmentCreate,
) -> Optional[DebtInstallment]:
    debt = await session.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        return None
    row = DebtInstallment(
        debt_id=debt.id,
        workspace_id=workspace_id,
        number=data.number,
        due_date=data.due_date,
        amount=data.amount,
        currency=data.currency,
        principal_amount=data.principal_amount,
        interest_amount=data.interest_amount,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
