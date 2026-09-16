import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.account import Account


class Debt(Base):
    """A loan or other liability tracked independently of credit-card bills."""

    __tablename__ = "debts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    creditor: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    principal: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    outstanding_balance: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    interest_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=8, scale=4), nullable=True)
    indexer: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    origination_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    collateral: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    product: Mapped[str] = mapped_column(String(40), default="outro")
    delinquency_status: Mapped[str] = mapped_column(String(20), default="em_dia")
    days_past_due: Mapped[int] = mapped_column(Integer, default=0)
    penalty_amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    installment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    remaining_term_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cet_annual_informed: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=10, scale=4), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    guarantee: Mapped[str] = mapped_column(String(40), default="nenhuma")
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    payoff_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_assumptions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="confirmed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    installments: Mapped[list["DebtInstallment"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )
    payments: Mapped[list["DebtPayment"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )
    offers: Mapped[list["DebtOffer"]] = relationship(
        back_populates="debt", cascade="all, delete-orphan"
    )
    account: Mapped[Optional["Account"]] = relationship()


class DebtInstallment(Base):
    __tablename__ = "debt_installments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    principal_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    interest_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    debt: Mapped["Debt"] = relationship(back_populates="installments")


class DebtPayment(Base):
    __tablename__ = "debt_payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    principal_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    interest_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=15, scale=2), nullable=True)
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    debt: Mapped["Debt"] = relationship(back_populates="payments")


class DebtCashPlan(Base):
    """Workspace cash envelope used to authorize a renegotiated installment."""

    __tablename__ = "debt_cash_plans"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_debt_cash_plans_workspace"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    income: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    variable_income: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    essential: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    discretionary: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    reserve: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    shock: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    steps: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DebtOffer(Base):
    """A written creditor offer compared against current terms. Not a ledger row."""

    __tablename__ = "debt_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debts.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(20), default="outro")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    payoff: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    cet_monthly: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=10, scale=4), nullable=True)
    installment: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), nullable=False)
    term_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    down_payment: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    waiver: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2), default=Decimal("0.00"))
    grace: Mapped[str] = mapped_column(String(20), default="nao")
    new_guarantee: Mapped[bool] = mapped_column(Boolean, default=False)
    operational_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    debt: Mapped["Debt"] = relationship(back_populates="offers")
