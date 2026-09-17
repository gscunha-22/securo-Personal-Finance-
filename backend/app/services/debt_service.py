import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.debt import Debt, DebtCashPlan, DebtInstallment, DebtOffer, DebtPayment
from app.services import audit_service, renegotiation as engine


async def _workspace_account(
    session: AsyncSession, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> Account:
    account = await session.scalar(
        select(Account).where(Account.id == account_id, Account.workspace_id == workspace_id)
    )
    if account is None:
        raise ValueError("Account not found in this workspace")
    return account


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
    product: str = "outro"
    delinquency_status: str = "em_dia"
    days_past_due: int = 0
    penalty_amount: Decimal = Decimal("0.00")
    installment_amount: Optional[Decimal] = None
    remaining_term_months: Optional[int] = None
    cet_annual_informed: Optional[Decimal] = None
    due_date: Optional[date] = None
    guarantee: str = "nenhuma"


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
    product: Optional[str] = None
    delinquency_status: Optional[str] = None
    days_past_due: Optional[int] = None
    penalty_amount: Optional[Decimal] = None
    installment_amount: Optional[Decimal] = None
    remaining_term_months: Optional[int] = None
    cet_annual_informed: Optional[Decimal] = None
    due_date: Optional[date] = None
    guarantee: Optional[str] = None


class DebtPaymentCreate(BaseModel):
    paid_on: date
    amount: Decimal = Field(gt=0)
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
    product: str = "outro"
    delinquency_status: str = "em_dia"
    days_past_due: int = 0
    penalty_amount: Decimal = Decimal("0.00")
    installment_amount: Optional[Decimal] = None
    remaining_term_months: Optional[int] = None
    cet_annual_informed: Optional[Decimal] = None
    due_date: Optional[date] = None
    guarantee: str = "nenhuma"


class CashPlanBody(BaseModel):
    income: Decimal = Decimal("0")
    variable_income: Decimal = Decimal("0")
    essential: Decimal = Decimal("0")
    discretionary: Decimal = Decimal("0")
    reserve: Decimal = Decimal("0")
    shock: Decimal = Decimal("0")


class OfferCreate(BaseModel):
    debt_id: uuid.UUID
    path: str = "outro"
    name: str
    payoff: Decimal
    cet_monthly: Optional[Decimal] = None
    installment: Decimal
    term_months: Optional[int] = None
    down_payment: Decimal = Decimal("0")
    waiver: Decimal = Decimal("0")
    grace: str = "nao"
    new_guarantee: bool = False
    operational_notes: Optional[str] = None


class StepsBody(BaseModel):
    steps: dict[str, bool]


class AmortizeBody(BaseModel):
    debt_id: uuid.UUID
    lump: Decimal = Decimal("0")
    extra: Decimal = Decimal("0")
    source: str = "recuperacao"


class PmtHintBody(BaseModel):
    payoff: Decimal
    down_payment: Decimal = Decimal("0")
    waiver: Decimal = Decimal("0")
    cet_monthly: Decimal
    term_months: int = Field(ge=1)


class ExampleBody(BaseModel):
    replace: bool = False
    currency: str = "BRL"


def _snapshot_debt(debt: Debt) -> engine.DebtSnapshot:
    return engine.DebtSnapshot(
        id=str(debt.id),
        creditor=debt.creditor,
        product=debt.product or "outro",
        payoff=debt.outstanding_balance,
        rate=debt.interest_rate,
        cet_annual_informed=debt.cet_annual_informed,
        installment=debt.installment_amount or Decimal("0"),
        term=debt.remaining_term_months,
        delinquency_status=debt.delinquency_status or "em_dia",
        dpd=debt.days_past_due or 0,
        penalty=debt.penalty_amount or Decimal("0"),
        guarantee=debt.guarantee or "nenhuma",
        notes=debt.notes or "",
        due=debt.due_date.isoformat() if debt.due_date else None,
        currency=debt.currency,
    )


def _snapshot_offer(offer: DebtOffer) -> engine.OfferSnapshot:
    return engine.OfferSnapshot(
        id=str(offer.id),
        debt_id=str(offer.debt_id),
        path=offer.path,
        name=offer.name,
        payoff=offer.payoff,
        cet=offer.cet_monthly,
        pmt=offer.installment,
        n=offer.term_months,
        down=offer.down_payment or Decimal("0"),
        waiver=offer.waiver or Decimal("0"),
        grace=offer.grace or "nao",
        new_guarantee=bool(offer.new_guarantee),
        ops=offer.operational_notes or "",
    )


def _snapshot_cash(plan: DebtCashPlan | None) -> engine.CashSnapshot:
    if not plan:
        return engine.CashSnapshot()
    return engine.CashSnapshot(
        income=plan.income or Decimal("0"),
        variable_income=plan.variable_income or Decimal("0"),
        essential=plan.essential or Decimal("0"),
        discretionary=plan.discretionary or Decimal("0"),
        reserve=plan.reserve or Decimal("0"),
        shock=plan.shock or Decimal("0"),
    )


async def list_debts(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> list[Debt]:
    query = (
        select(Debt)
        .where(Debt.workspace_id == workspace_id)
        .order_by(Debt.created_at.desc())
    )
    if limit is not None:
        query = query.offset(offset).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_debt(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: DebtCreate,
) -> Debt:
    payload = data.model_dump()
    account_id = payload.pop("account_id")
    if account_id is not None:
        await _workspace_account(session, workspace_id, account_id)
    debt = Debt(
        user_id=user_id,
        workspace_id=workspace_id,
        account_id=account_id,
        status="active",
        source="manual",
        review_status="confirmed",
        **payload,
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


async def delete_debt(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    debt_id: uuid.UUID,
) -> bool:
    debt = await session.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        return False
    name = debt.name
    await session.delete(debt)
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.delete",
        entity_type="debt",
        entity_id=debt_id,
        summary=f"Deleted debt {name}",
    )
    await session.commit()
    return True


async def add_payment(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    debt_id: uuid.UUID,
    data: DebtPaymentCreate,
) -> Optional[DebtPayment]:
    debt = await session.scalar(
        select(Debt).where(Debt.id == debt_id, Debt.workspace_id == workspace_id).with_for_update()
    )
    if not debt:
        return None
    if data.amount <= 0:
        raise ValueError("Payment amount must be positive")
    if data.currency.upper() != debt.currency.upper():
        raise ValueError("Payment currency must match the debt currency")
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
    payment.debt = debt
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
    await session.refresh(debt)
    payment.debt = debt
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


async def _cash_plan(session: AsyncSession, workspace_id: uuid.UUID) -> DebtCashPlan | None:
    return await session.scalar(select(DebtCashPlan).where(DebtCashPlan.workspace_id == workspace_id))


async def _offers(session: AsyncSession, workspace_id: uuid.UUID) -> list[DebtOffer]:
    result = await session.execute(select(DebtOffer).where(DebtOffer.workspace_id == workspace_id))
    return list(result.scalars().all())


async def get_plan(session: AsyncSession, workspace_id: uuid.UUID) -> dict:
    debts = await list_debts(session, workspace_id)
    offers = await _offers(session, workspace_id)
    plan = await _cash_plan(session, workspace_id)
    return engine.build_plan(
        [_snapshot_debt(d) for d in debts],
        [_snapshot_offer(o) for o in offers],
        _snapshot_cash(plan),
        (plan.steps or {}) if plan else {},
    )


async def upsert_cash(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CashPlanBody,
) -> dict:
    plan = await _cash_plan(session, workspace_id)
    if not plan:
        plan = DebtCashPlan(user_id=user_id, workspace_id=workspace_id, steps={})
        session.add(plan)
    plan.income = data.income
    plan.variable_income = data.variable_income
    plan.essential = data.essential
    plan.discretionary = data.discretionary
    plan.reserve = data.reserve
    plan.shock = data.shock
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.cash.update",
        entity_type="debt_cash_plan",
        entity_id=plan.id,
        summary="Updated 12-month cash envelope",
    )
    await session.commit()
    return await get_plan(session, workspace_id)


async def create_offer(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: OfferCreate,
) -> dict:
    debt = await session.scalar(
        select(Debt).where(Debt.id == data.debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        raise LookupError("Debt not found")
    offer = DebtOffer(
        debt_id=debt.id,
        workspace_id=workspace_id,
        path=data.path,
        name=data.name,
        payoff=data.payoff,
        cet_monthly=data.cet_monthly,
        installment=data.installment,
        term_months=data.term_months,
        down_payment=data.down_payment,
        waiver=data.waiver,
        grace=data.grace,
        new_guarantee=data.new_guarantee,
        operational_notes=data.operational_notes,
    )
    session.add(offer)
    await session.flush()
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.offer.create",
        entity_type="debt_offer",
        entity_id=offer.id,
        summary=f"Recorded offer {offer.name}",
    )
    await session.commit()
    return await get_plan(session, workspace_id)


async def delete_offer(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    offer_id: uuid.UUID,
) -> dict | None:
    offer = await session.scalar(
        select(DebtOffer).where(DebtOffer.id == offer_id, DebtOffer.workspace_id == workspace_id)
    )
    if not offer:
        return None
    await session.delete(offer)
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.offer.delete",
        entity_type="debt_offer",
        entity_id=offer_id,
        summary="Deleted a written offer",
    )
    await session.commit()
    return await get_plan(session, workspace_id)


async def update_steps(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: StepsBody,
) -> dict:
    plan = await _cash_plan(session, workspace_id)
    if not plan:
        plan = DebtCashPlan(user_id=user_id, workspace_id=workspace_id)
        session.add(plan)
    cleaned = {key: bool(data.steps.get(key)) for key in engine.EXECUTION_STEPS}
    plan.steps = cleaned
    await session.commit()
    return await get_plan(session, workspace_id)


async def simulate_amortize(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    data: AmortizeBody,
) -> dict:
    debt = await session.scalar(
        select(Debt).where(Debt.id == data.debt_id, Debt.workspace_id == workspace_id)
    )
    if not debt:
        raise LookupError("Debt not found")
    offers = await _offers(session, workspace_id)
    plan = await _cash_plan(session, workspace_id)
    debts = [_snapshot_debt(d) for d in await list_debts(session, workspace_id)]
    sc = engine.scenarios(debts, [_snapshot_offer(o) for o in offers], _snapshot_cash(plan))
    result = engine.amortize(
        _snapshot_debt(debt),
        data.lump,
        data.extra,
        data.source,
        _snapshot_cash(plan),
        sc,
    )
    if result.get("ok"):
        for key in ("baseline", "quit", "keep_term", "cut_pmt"):
            result[key] = engine.serialize_sim(result[key])
        result["save_keep"] = engine.json_money(result["save_keep"])
        result["save_cut"] = engine.json_money(result["save_cut"])
        result["rec_surplus"] = engine.json_money(result["rec_surplus"])
        terms = result["terms"]
        result["terms"] = {
            "i": engine.json_rate(terms["i"]),
            "pv": engine.json_money(terms["pv"]),
            "pmt": engine.json_money(terms["pmt"]),
            "n": terms["n"],
        }
    else:
        result["rec_surplus"] = engine.json_money(result["rec_surplus"])
    result["avalanche"] = engine.avalanche(debts, data.lump, data.extra)
    if result["avalanche"] and result["avalanche"].get("interest_saved") is not None:
        result["avalanche"]["interest_saved"] = engine.json_money(result["avalanche"]["interest_saved"])
        result["avalanche"]["rate"] = engine.json_rate(result["avalanche"]["rate"])
    elif result["avalanche"]:
        result["avalanche"]["rate"] = engine.json_rate(result["avalanche"].get("rate"))
    return result


def pmt_hint(data: PmtHintBody) -> dict:
    value = engine.theoretical_pmt(
        data.payoff, data.down_payment, data.waiver, data.cet_monthly, data.term_months
    )
    cet_a = engine.cet_annual_from_monthly(data.cet_monthly)
    return {"pmt": engine.json_money(value), "cet_annual": engine.json_rate(cet_a)}


async def seed_example(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ExampleBody,
) -> dict:
    existing = await list_debts(session, workspace_id)
    if existing and not data.replace:
        raise ValueError("replace_required")
    if existing and data.replace:
        await session.execute(delete(Debt).where(Debt.workspace_id == workspace_id))
        await session.flush()
    for row in engine.EXAMPLE_DEBTS:
        payoff = Decimal(str(row["payoff"]))
        session.add(
            Debt(
                user_id=user_id,
                workspace_id=workspace_id,
                name=str(row["creditor"]),
                creditor=str(row["creditor"]),
                currency=data.currency,
                principal=payoff,
                outstanding_balance=payoff,
                interest_rate=Decimal(str(row["rate"])),
                installment_amount=Decimal(str(row["installment"])),
        remaining_term_months=int(row["term"]) if row.get("term") is not None else None,
                product=str(row["product"]),
                delinquency_status=str(row["delinquency_status"]),
                days_past_due=int(row["dpd"]),
                notes=str(row.get("notes") or ""),
                guarantee="nenhuma",
                source="example",
                review_status="confirmed",
                strategy_assumptions="Didactic example. Ignores tax effects; not a recommendation.",
            )
        )
    plan = await _cash_plan(session, workspace_id)
    if not plan:
        plan = DebtCashPlan(user_id=user_id, workspace_id=workspace_id, steps={})
        session.add(plan)
    plan.income = Decimal(engine.EXAMPLE_CASH["income"])
    plan.variable_income = Decimal(engine.EXAMPLE_CASH["variable_income"])
    plan.essential = Decimal(engine.EXAMPLE_CASH["essential"])
    plan.discretionary = Decimal(engine.EXAMPLE_CASH["discretionary"])
    plan.reserve = Decimal(engine.EXAMPLE_CASH["reserve"])
    plan.shock = Decimal(engine.EXAMPLE_CASH["shock"])
    await audit_service.record(
        session,
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="debt.example.seed",
        entity_type="debt",
        entity_id=workspace_id,
        summary="Loaded didactic debt-renegotiation example",
    )
    await session.commit()
    return await get_plan(session, workspace_id)
