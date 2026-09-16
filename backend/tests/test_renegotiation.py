from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.services.renegotiation import (
    CashSnapshot,
    DebtSnapshot,
    OfferSnapshot,
    build_plan,
    cet_annual_from_monthly,
    pmt,
    simulate_price,
)


def _debt(
    *,
    id: str = "d1",
    creditor: str = "Bank",
    product: str = "rotativo",
    payoff: Decimal = Decimal("12000"),
    rate: Decimal | None = Decimal("14"),
    installment: Decimal = Decimal("360"),
    term: int | None = None,
    delinquency_status: str = "atraso",
    dpd: int = 90,
    notes: str = "",
) -> DebtSnapshot:
    return DebtSnapshot(
        id=id,
        creditor=creditor,
        product=product,
        payoff=payoff,
        rate=rate,
        cet_annual_informed=None,
        installment=installment,
        term=term,
        delinquency_status=delinquency_status,
        dpd=dpd,
        penalty=Decimal("0"),
        guarantee="nenhuma",
        notes=notes,
    )


def test_cet_annual_from_monthly_is_compound_not_simple():
    cet = cet_annual_from_monthly(Decimal("14"))
    assert cet is not None
    # (1.14^12 - 1) * 100 ≈ 381.77, not 14*12 = 168
    assert Decimal("380") < cet < Decimal("383")
    assert cet != Decimal("168")


def test_price_pmt_zero_rate_is_straight_line():
    assert pmt(Decimal("1200"), Decimal("0"), 12) == Decimal("100.00")


def test_minimum_at_or_below_interest_never_amortizes():
    result = simulate_price(Decimal("12000"), Decimal("14"), Decimal("360"))
    assert result["never"] is True
    extra = simulate_price(Decimal("12000"), Decimal("14"), Decimal("360"), extra_m=Decimal("1400"))
    assert extra["never"] is False
    assert extra["months"] and extra["months"] < 480


def test_priority_is_rate_and_arrears_not_balance():
    cheap_big = _debt(
        id="loan",
        creditor="Loan",
        product="emprestimo",
        payoff=Decimal("20000"),
        rate=Decimal("6"),
        installment=Decimal("800"),
        delinquency_status="em_dia",
        dpd=0,
    )
    expensive_small = _debt(
        id="card",
        creditor="Card",
        product="rotativo",
        payoff=Decimal("8000"),
        rate=Decimal("13"),
        installment=Decimal("240"),
        delinquency_status="atraso",
        dpd=45,
    )
    plan = build_plan([cheap_big, expensive_small], [], CashSnapshot())
    assert plan["debts"][0]["creditor"] == "Card"
    assert plan["debts"][0]["priority"] == 1
    assert plan["debts"][1]["creditor"] == "Loan"


def test_conservative_cash_authorizes_and_thirty_is_filter_only():
    debts = [
        _debt(),
        _debt(
            id="d2",
            creditor="Inter",
            payoff=Decimal("8000"),
            rate=Decimal("13"),
            installment=Decimal("240"),
            dpd=45,
        ),
        _debt(
            id="d3",
            creditor="Nubank",
            payoff=Decimal("15000"),
            rate=Decimal("12"),
            installment=Decimal("450"),
            delinquency_status="em_dia",
            dpd=0,
        ),
        _debt(
            id="d4",
            creditor="Pan",
            product="cheque",
            payoff=Decimal("5000"),
            rate=Decimal("8"),
            installment=Decimal("400"),
            dpd=15,
        ),
        _debt(
            id="d5",
            creditor="Loan",
            product="emprestimo",
            payoff=Decimal("20000"),
            rate=Decimal("6"),
            installment=Decimal("800"),
            delinquency_status="em_dia",
            dpd=0,
            term=24,
        ),
    ]
    cash = CashSnapshot(
        income=Decimal("12000"),
        essential=Decimal("6000"),
        shock=Decimal("1500"),
    )
    plan = build_plan(debts, [], cash)
    sc = plan["scenarios"]
    assert sc["service"] == "2250.00"
    assert sc["cap_cons"] == "4500.00"
    assert sc["cons_free"] == "2250.00"
    assert sc["ceiling30"] == "3600.00"
    assert sc["filter30_ok"] is True
    gate_ids = [item["id"] for item in plan["gates"]["items"]]
    assert "filter30" not in gate_ids
    assert plan["gates"]["filter30"]["auxiliary"] is True
    assert plan["gates"]["ready"] is False
    paths = {row["id"]: row["applicable"] for row in plan["paths"]}
    assert paths["keep"] is False
    assert paths["arrears"] is True
    assert paths["swap"] is True


def test_offer_that_breaks_conservative_is_not_ready():
    debt = _debt(installment=Decimal("2250"), payoff=Decimal("20000"), rate=Decimal("14"))
    cash = CashSnapshot(income=Decimal("12000"), essential=Decimal("6000"), shock=Decimal("1500"))
    offer = OfferSnapshot(
        id="o1",
        debt_id="d1",
        path="troca",
        name="18x",
        payoff=Decimal("20000"),
        cet=Decimal("3"),
        pmt=Decimal("4501"),
        n=18,
        down=Decimal("0"),
        waiver=Decimal("0"),
        grace="nao",
        new_guarantee=False,
        ops="",
    )
    plan = build_plan([debt], [offer], cash, {"s7": True})
    assert plan["scenarios"]["cons_free_r"] == "-1.00"
    conservative = next(item for item in plan["gates"]["items"] if item["id"] == "conservative")
    assert conservative["ok"] is False
    assert plan["gates"]["ready"] is False
    assert plan["offers"][0]["fits_conservative"] is False


def test_five_gates_pass_only_with_documented_cheaper_offer_and_s7():
    debt = _debt(installment=Decimal("2000"), payoff=Decimal("10000"), rate=Decimal("14"))
    cash = CashSnapshot(income=Decimal("12000"), essential=Decimal("6000"), shock=Decimal("1500"))
    offer = OfferSnapshot(
        id="o1",
        debt_id="d1",
        path="atraso",
        name="Amnesty",
        payoff=Decimal("10000"),
        cet=Decimal("4"),
        pmt=Decimal("900"),
        n=12,
        down=Decimal("0"),
        waiver=Decimal("500"),
        grace="nao",
        new_guarantee=False,
        ops="written CET",
    )
    before = build_plan([debt], [offer], cash, {})
    assert before["gates"]["ready"] is False
    after = build_plan([debt], [offer], cash, {"s7": True})
    assert all(item["ok"] for item in after["gates"]["items"])
    assert after["gates"]["ready"] is True
    assert after["offers"][0]["material"] is True


@pytest.mark.asyncio
async def test_renegotiation_plan_example_and_offer_gate(client: AsyncClient, auth_headers):
    empty = await client.get("/api/renegotiation", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["totals"]["count"] == 0

    blocked = await client.post(
        "/api/renegotiation/example",
        headers=auth_headers,
        json={"replace": False, "currency": "BRL"},
    )
    assert blocked.status_code == 201 or blocked.status_code == 200, blocked.text
    plan = blocked.json()
    assert plan["totals"]["count"] == 5
    assert plan["scenarios"]["service"] == "2250.00"
    assert plan["scenarios"]["cons_free"] == "2250.00"
    assert plan["gates"]["filter30"]["auxiliary"] is True
    assert plan["gates"]["ready"] is False
    assert plan["debts"][0]["creditor"] == "Santander"

    again = await client.post(
        "/api/renegotiation/example",
        headers=auth_headers,
        json={"replace": False},
    )
    assert again.status_code == 409

    debt_id = plan["debts"][0]["id"]
    offer = await client.post(
        "/api/renegotiation/offers",
        headers=auth_headers,
        json={
            "debt_id": debt_id,
            "path": "atraso",
            "name": "Amnesty 12x",
            "payoff": "12000.00",
            "cet_monthly": "3.5",
            "installment": "1100.00",
            "term_months": 12,
            "waiver": "400.00",
            "new_guarantee": False,
        },
    )
    assert offer.status_code == 200, offer.text
    offered = offer.json()
    assert offered["offers"][0]["material"] is True
    assert offered["offers"][0]["fits_conservative"] is True

    steps = await client.put(
        "/api/renegotiation/steps",
        headers=auth_headers,
        json={"steps": {"s7": True}},
    )
    assert steps.status_code == 200
    assert steps.json()["gates"]["items"][-1]["ok"] is True

    hint = await client.post(
        "/api/renegotiation/pmt-hint",
        headers=auth_headers,
        json={
            "payoff": "10000",
            "cet_monthly": "2",
            "term_months": 12,
        },
    )
    assert hint.status_code == 200
    assert Decimal(hint.json()["pmt"]) > 0

    amort = await client.post(
        "/api/renegotiation/amortize",
        headers=auth_headers,
        json={"debt_id": debt_id, "lump": "0", "extra": "1500", "source": "recuperacao"},
    )
    assert amort.status_code == 200, amort.text
    body = amort.json()
    assert body["ok"] is True
    assert body["baseline"]["never"] is True
    assert body["keep_term"]["never"] is False


@pytest.mark.asyncio
async def test_create_inventory_debt_with_product(client: AsyncClient, auth_headers):
    created = await client.post(
        "/api/debts",
        headers=auth_headers,
        json={
            "name": "Card",
            "creditor": "Issuer",
            "currency": "BRL",
            "principal": "5000.00",
            "outstanding_balance": "5000.00",
            "interest_rate": "12.5",
            "product": "rotativo",
            "delinquency_status": "atraso",
            "days_past_due": 40,
            "installment_amount": "200.00",
            "guarantee": "nenhuma",
        },
    )
    assert created.status_code == 201, created.text
    plan = (await client.get("/api/renegotiation", headers=auth_headers)).json()
    assert plan["debts"][0]["product"] == "rotativo"
    assert plan["debts"][0]["priority"] == 1
    deleted = await client.delete(f"/api/debts/{created.json()['id']}", headers=auth_headers)
    assert deleted.status_code == 204

