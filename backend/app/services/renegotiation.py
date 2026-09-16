"""Deterministic debt-renegotiation math.

Numbers come from the inventory, cash plan and written offers. Nothing here
invents rates, balances or dates. CET estimated from a monthly rate is an
approximation until the creditor states CET; conservative cash — not the 30%
income filter — authorizes an installment.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import inf, log
from typing import Any, Mapping, Sequence

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
THIRTY = Decimal("0.3")
MAX_MONTHS = 480
EPS = Decimal("0.005")

PRODUCT_RANK = {
    "rotativo": 1,
    "parcelamento": 1,
    "cheque": 1,
    "emprestimo": 3,
    "consignado": 3,
    "financiamento": 3,
    "outro": 4,
}

EXECUTION_STEPS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7")
ALERT_KEYS = (
    "entryEatsReserve",
    "noCet",
    "essentialCollateral",
    "newCreditForBills",
    "unofficialBroker",
    "higherPmtBreaksConservative",
)
PATH_KEYS = ("keep", "arrears", "swap")


def as_dec(value: object, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def rate(value: Decimal) -> Decimal:
    return value.quantize(RATE, rounding=ROUND_HALF_UP)


def json_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(money(value))


def json_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(rate(value))


@dataclass(frozen=True)
class DebtSnapshot:
    id: str
    creditor: str
    product: str
    payoff: Decimal
    rate: Decimal | None
    cet_annual_informed: Decimal | None
    installment: Decimal
    term: int | None
    delinquency_status: str
    dpd: int
    penalty: Decimal
    guarantee: str
    notes: str
    due: str | None = None
    currency: str = "BRL"


@dataclass(frozen=True)
class OfferSnapshot:
    id: str
    debt_id: str
    path: str
    name: str
    payoff: Decimal
    cet: Decimal | None
    pmt: Decimal
    n: int | None
    down: Decimal
    waiver: Decimal
    grace: str
    new_guarantee: bool
    ops: str


@dataclass(frozen=True)
class CashSnapshot:
    income: Decimal = ZERO
    variable_income: Decimal = ZERO
    essential: Decimal = ZERO
    discretionary: Decimal = ZERO
    reserve: Decimal = ZERO
    shock: Decimal = ZERO


def cet_annual_from_monthly(i_pct: Decimal | None) -> Decimal | None:
    if i_pct is None:
        return None
    i = i_pct / HUNDRED
    return rate(((Decimal("1") + i) ** 12 - Decimal("1")) * HUNDRED)


def pmt(pv: Decimal, i_pct: Decimal, n: int) -> Decimal:
    if pv <= 0 or n <= 0:
        return ZERO
    i = i_pct / HUNDRED
    if i == 0:
        return money(pv / Decimal(n))
    factor = (Decimal("1") + i) ** n
    return money(pv * i * factor / (factor - Decimal("1")))


def nper_from(pv: Decimal, i_pct: Decimal, pmt_val: Decimal) -> float:
    if pv <= 0:
        return 0.0
    i = i_pct / HUNDRED
    if i == 0:
        if pmt_val <= 0:
            return inf
        return float((pv / pmt_val).to_integral_value(rounding=ROUND_HALF_UP))
    monthly = pv * i
    if pmt_val <= monthly:
        return inf
    ratio = float(pmt_val / (pmt_val - monthly))
    return log(ratio) / log(float(Decimal("1") + i))


def debt_priority(debt: DebtSnapshot) -> int:
    score = PRODUCT_RANK.get(debt.product, 4)
    if debt.rate is not None and debt.rate >= Decimal("5"):
        score = min(score, 1)
    if debt.delinquency_status != "em_dia":
        score = min(score, 2)
    if debt.dpd >= 30:
        score = min(score, 1)
    if debt.guarantee != "nenhuma" and debt.delinquency_status != "em_dia":
        score = min(score, 2)
    return score


def sort_debts(debts: Sequence[DebtSnapshot]) -> list[DebtSnapshot]:
    def key(debt: DebtSnapshot) -> tuple[int, Decimal, int]:
        rate_val = debt.rate if debt.rate is not None else Decimal("-1")
        return (debt_priority(debt), -rate_val, -debt.dpd)

    return sorted(debts, key=key)


def effective_cet_annual(debt: DebtSnapshot) -> Decimal | None:
    if debt.cet_annual_informed is not None:
        return rate(debt.cet_annual_informed)
    return cet_annual_from_monthly(debt.rate)


def current_service(debts: Sequence[DebtSnapshot]) -> Decimal:
    return money(sum((debt.installment for debt in debts), ZERO))


def offer_service(debts: Sequence[DebtSnapshot], offers: Sequence[OfferSnapshot]) -> Decimal | None:
    if not offers:
        return None
    covered = {offer.debt_id for offer in offers}
    rest = sum((debt.installment for debt in debts if debt.id not in covered), ZERO)
    neu = sum((offer.pmt for offer in offers), ZERO)
    return money(rest + neu)


def scenarios(
    debts: Sequence[DebtSnapshot],
    offers: Sequence[OfferSnapshot],
    cash: CashSnapshot,
) -> dict[str, Any]:
    service = current_service(debts)
    reneg = offer_service(debts, offers)
    income = cash.income
    cap_cons = money(income - cash.shock - cash.essential - cash.reserve - cash.discretionary)
    cap_base = money(income - cash.essential - cash.reserve - cash.discretionary)
    pre = money(income - cash.essential - cash.reserve)
    commit = rate((service / income) * HUNDRED) if income else ZERO
    commit_r = rate((reneg / income) * HUNDRED) if income and reneg is not None else None
    ceiling30 = money(income * THIRTY)
    return {
        "service": service,
        "reneg": reneg,
        "pre": pre,
        "cap_cons": cap_cons,
        "cap_base": cap_base,
        "base_free": money(cap_base - service),
        "cons_free": money(cap_cons - service),
        "rec_free": money(cap_base + cash.variable_income - service),
        "base_free_r": None if reneg is None else money(cap_base - reneg),
        "cons_free_r": None if reneg is None else money(cap_cons - reneg),
        "commit": commit,
        "commit_r": commit_r,
        "ceiling30": ceiling30,
        "filter30_ok": (reneg if reneg is not None else service) <= ceiling30,
    }


def paths(
    debts: Sequence[DebtSnapshot],
    sc: Mapping[str, Any],
) -> list[dict[str, Any]]:
    hot_arrears = any(debt_priority(d) == 1 and d.dpd > 0 for d in debts)
    keep_ok = sc["cons_free"] >= 0 and not hot_arrears
    arrears_ok = any(d.dpd > 0 or d.delinquency_status != "em_dia" for d in debts)
    swap_ok = any(d.product in {"rotativo", "parcelamento", "cheque"} for d in debts)
    arrears_n = sum(1 for d in debts if d.dpd > 0 or d.delinquency_status != "em_dia")
    return [
        {"id": "keep", "applicable": keep_ok, "metric": "cons_free"},
        {"id": "arrears", "applicable": arrears_ok, "arrears_count": arrears_n},
        {"id": "swap", "applicable": swap_ok, "metric": "cap_cons"},
    ]


def offer_metrics(offer: OfferSnapshot) -> dict[str, Any]:
    total = money(offer.down + offer.pmt * Decimal(offer.n or 0))
    extra = money(total - offer.payoff + offer.waiver)
    return {
        "total": total,
        "extra": extra,
        "cet_annual": cet_annual_from_monthly(offer.cet),
    }


def theoretical_pmt(payoff: Decimal, down: Decimal, waiver: Decimal, cet: Decimal, n: int) -> Decimal:
    pv = payoff - down - waiver
    return pmt(pv, cet, n)


def simulate_price(
    pv: Decimal,
    i_pct: Decimal,
    pmt_val: Decimal,
    lump: Decimal = ZERO,
    extra_m: Decimal = ZERO,
    mode: str = "manter",
    max_m: int = MAX_MONTHS,
) -> dict[str, Any]:
    i = i_pct / HUNDRED
    bal = max(ZERO, pv - lump)
    pay = pmt_val
    if mode == "reduzir_parcela":
        n0 = nper_from(pv, i_pct, pmt_val)
        if n0 != inf and n0 > 0:
            pay = pmt(bal, i_pct, int(Decimal(str(n0)).to_integral_value(rounding=ROUND_HALF_UP)))
    scheduled = pay
    pay = scheduled + extra_m
    months = 0
    interest = ZERO
    paid = lump
    if bal <= EPS:
        return {
            "months": 0,
            "interest": ZERO,
            "paid": money(paid),
            "new_pmt": ZERO,
            "bal": ZERO,
            "never": False,
        }
    if i > 0 and pay <= bal * i:
        return {
            "months": None,
            "interest": None,
            "paid": money(paid),
            "new_pmt": money(pay),
            "bal": money(bal),
            "never": True,
        }
    while bal > EPS and months < max_m:
        ju = bal * i if i else ZERO
        due = min(pay, bal + ju)
        prin = due - ju
        if prin <= 0:
            return {
                "months": None,
                "interest": None,
                "paid": money(paid),
                "new_pmt": money(pay),
                "bal": money(bal),
                "never": True,
            }
        bal = max(ZERO, bal - prin)
        interest += ju
        paid += due
        months += 1
    never = months >= max_m
    return {
        "months": None if never else months,
        "interest": None if never else money(interest),
        "paid": money(paid),
        "new_pmt": money(scheduled if mode == "reduzir_parcela" else pay),
        "bal": money(bal),
        "never": never,
    }


def debt_terms(debt: DebtSnapshot) -> dict[str, Any]:
    if debt.rate is None:
        return {"ok": False, "reason": "missing_rate"}
    if debt.payoff <= 0:
        return {"ok": False, "reason": "missing_payoff"}
    pmt_val = debt.installment
    n = debt.term
    if pmt_val <= 0 and n:
        pmt_val = pmt(debt.payoff, debt.rate, n)
    if (n is None or n <= 0) and pmt_val > 0:
        n0 = nper_from(debt.payoff, debt.rate, pmt_val)
        n = None if n0 == inf else int(n0)
    if pmt_val <= 0:
        return {"ok": False, "reason": "missing_pmt_or_term"}
    return {"ok": True, "i": debt.rate, "pv": debt.payoff, "pmt": pmt_val, "n": n}


def amortize(
    debt: DebtSnapshot,
    lump: Decimal,
    extra: Decimal,
    source: str,
    cash: CashSnapshot,
    sc: Mapping[str, Any],
) -> dict[str, Any]:
    terms = debt_terms(debt)
    rec_surplus = max(ZERO, sc["rec_free"])
    if not terms["ok"]:
        return {
            "ok": False,
            "reason": terms["reason"],
            "rec_surplus": rec_surplus,
            "source": source,
        }
    base = simulate_price(terms["pv"], terms["i"], terms["pmt"], ZERO, ZERO, "manter")
    keep = simulate_price(terms["pv"], terms["i"], terms["pmt"], lump, extra, "manter")
    cut = simulate_price(terms["pv"], terms["i"], terms["pmt"], lump, extra, "reduzir_parcela")
    quit_now = {
        "months": 0,
        "interest": ZERO,
        "paid": money(terms["pv"]),
        "new_pmt": ZERO,
        "bal": ZERO,
        "never": False,
    }
    save_keep = None
    if base["interest"] is not None and keep["interest"] is not None:
        save_keep = money(base["interest"] - keep["interest"])
    save_cut = None
    if base["interest"] is not None and cut["interest"] is not None:
        save_cut = money(base["interest"] - cut["interest"])
    extra_fits = extra <= rec_surplus or extra == 0
    return {
        "ok": True,
        "source": source,
        "rec_surplus": rec_surplus,
        "extra_fits_recovery": extra_fits,
        "uses_reserve": source == "reserva",
        "uses_base": source == "base",
        "save_keep": save_keep,
        "save_cut": save_cut,
        "baseline": base,
        "quit": quit_now,
        "keep_term": keep,
        "cut_pmt": cut,
        "terms": {"i": terms["i"], "pv": terms["pv"], "pmt": terms["pmt"], "n": terms["n"]},
    }


def avalanche(
    debts: Sequence[DebtSnapshot],
    lump: Decimal,
    extra: Decimal,
) -> dict[str, Any] | None:
    ranked = sorted(debts, key=lambda d: d.rate if d.rate is not None else Decimal("-1"), reverse=True)
    if not ranked:
        return None
    target = ranked[0]
    terms = debt_terms(target)
    payload: dict[str, Any] = {
        "debt_id": target.id,
        "creditor": target.creditor,
        "rate": target.rate,
        "method": "avalanche",
    }
    if not terms["ok"]:
        payload["reason"] = terms["reason"]
        return payload
    base = simulate_price(terms["pv"], terms["i"], terms["pmt"], ZERO, ZERO, "manter")
    keep = simulate_price(terms["pv"], terms["i"], terms["pmt"], lump, extra, "manter")
    payload["baseline_never"] = base["never"]
    payload["with_extra_never"] = keep["never"]
    payload["months"] = keep["months"]
    if base["interest"] is not None and keep["interest"] is not None:
        payload["interest_saved"] = money(base["interest"] - keep["interest"])
    return payload


def gates(
    debts: Sequence[DebtSnapshot],
    offers: Sequence[OfferSnapshot],
    sc: Mapping[str, Any],
    steps: Mapping[str, bool],
) -> dict[str, Any]:
    has_doc = any(o.cet is not None and o.n and o.pmt > 0 for o in offers)
    no_bad_g = not offers or all(not o.new_guarantee for o in offers)
    material = any(_offer_is_material(o, debts) for o in offers)
    gate_items = [
        {"id": "material", "ok": material or not offers},
        {
            "id": "conservative",
            "ok": sc["cons_free"] >= 0 if sc["reneg"] is None else sc["cons_free_r"] >= 0,
        },
        {"id": "documented", "ok": has_doc or not offers},
        {"id": "no_new_guarantee", "ok": no_bad_g},
        {"id": "no_revolve", "ok": bool(steps.get("s7"))},
    ]
    all_ok = all(item["ok"] for item in gate_items) and bool(offers)
    return {
        "items": gate_items,
        "filter30": {
            "ok": sc["filter30_ok"],
            "commit": sc["commit_r"] if sc["commit_r"] is not None else sc["commit"],
            "auxiliary": True,
        },
        "ready": all_ok,
    }


def _offer_is_material(offer: OfferSnapshot, debts: Sequence[DebtSnapshot]) -> bool:
    debt = next((d for d in debts if d.id == offer.debt_id), None)
    if not debt:
        return False
    cheaper_rate = offer.cet is not None and debt.rate is not None and offer.cet < debt.rate
    cheaper_pmt = offer.pmt < debt.installment
    return cheaper_rate or cheaper_pmt or offer.waiver > 0


def serialize_debt(debt: DebtSnapshot) -> dict[str, Any]:
    return {
        "id": debt.id,
        "creditor": debt.creditor,
        "product": debt.product,
        "payoff": json_money(debt.payoff),
        "rate": json_rate(debt.rate),
        "cet_annual_informed": json_rate(debt.cet_annual_informed),
        "cet_annual": json_rate(effective_cet_annual(debt)),
        "cet_is_estimate": debt.cet_annual_informed is None,
        "installment": json_money(debt.installment),
        "term": debt.term,
        "delinquency_status": debt.delinquency_status,
        "dpd": debt.dpd,
        "penalty": json_money(debt.penalty),
        "guarantee": debt.guarantee,
        "notes": debt.notes,
        "due": debt.due,
        "currency": debt.currency,
        "priority": debt_priority(debt),
    }


def serialize_offer(offer: OfferSnapshot, sc: Mapping[str, Any], debts: Sequence[DebtSnapshot]) -> dict[str, Any]:
    metrics = offer_metrics(offer)
    fits = offer.pmt <= sc["cap_cons"] and sc["cap_cons"] > 0
    debt = next((d for d in debts if d.id == offer.debt_id), None)
    return {
        "id": offer.id,
        "debt_id": offer.debt_id,
        "creditor": debt.creditor if debt else None,
        "path": offer.path,
        "name": offer.name,
        "payoff": json_money(offer.payoff),
        "cet": json_rate(offer.cet),
        "cet_annual": json_rate(metrics["cet_annual"]),
        "pmt": json_money(offer.pmt),
        "n": offer.n,
        "down": json_money(offer.down),
        "waiver": json_money(offer.waiver),
        "grace": offer.grace,
        "new_guarantee": offer.new_guarantee,
        "ops": offer.ops,
        "total": json_money(metrics["total"]),
        "extra": json_money(metrics["extra"]),
        "fits_conservative": fits,
        "material": _offer_is_material(offer, debts),
    }


def serialize_sim(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "months": row.get("months"),
        "interest": json_money(row["interest"]) if row.get("interest") is not None else None,
        "paid": json_money(row["paid"]) if row.get("paid") is not None else None,
        "new_pmt": json_money(row["new_pmt"]) if row.get("new_pmt") is not None else None,
        "bal": json_money(row["bal"]) if row.get("bal") is not None else None,
        "never": bool(row.get("never")),
    }


def cashflow_months(cash: CashSnapshot, sc: Mapping[str, Any], months: int = 12) -> list[dict[str, Any]]:
    rows = []
    fixed = money(cash.essential + cash.discretionary + cash.reserve)
    for month in range(1, months + 1):
        atual = money(cash.income - fixed - sc["service"])
        reneg = None if sc["reneg"] is None else money(cash.income - fixed - sc["reneg"])
        rows.append(
            {
                "month": month,
                "income": json_money(cash.income),
                "fixed": json_money(fixed),
                "service": json_money(sc["service"]),
                "reneg": json_money(sc["reneg"]),
                "balance": json_money(atual),
                "balance_reneg": json_money(reneg),
            }
        )
    return rows


def bank_script_facts(debts: Sequence[DebtSnapshot]) -> list[dict[str, Any]]:
    return [
        {
            "creditor": debt.creditor,
            "product": debt.product,
            "payoff": json_money(debt.payoff),
            "rate": json_rate(debt.rate),
            "cet_annual": json_rate(effective_cet_annual(debt)),
            "installment": json_money(debt.installment),
            "dpd": debt.dpd,
            "penalty": json_money(debt.penalty),
        }
        for debt in sort_debts(debts)
    ]


def build_plan(
    debts: Sequence[DebtSnapshot],
    offers: Sequence[OfferSnapshot],
    cash: CashSnapshot,
    steps: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    step_map = {key: bool((steps or {}).get(key)) for key in EXECUTION_STEPS}
    ordered = sort_debts(debts)
    sc = scenarios(ordered, offers, cash)
    total = money(sum((d.payoff for d in ordered), ZERO))
    hot = sum(1 for d in ordered if debt_priority(d) == 1)
    serialized_sc = {
        "service": json_money(sc["service"]),
        "reneg": json_money(sc["reneg"]),
        "pre": json_money(sc["pre"]),
        "cap_cons": json_money(sc["cap_cons"]),
        "cap_base": json_money(sc["cap_base"]),
        "base_free": json_money(sc["base_free"]),
        "cons_free": json_money(sc["cons_free"]),
        "rec_free": json_money(sc["rec_free"]),
        "base_free_r": json_money(sc["base_free_r"]),
        "cons_free_r": json_money(sc["cons_free_r"]),
        "commit": json_rate(sc["commit"]),
        "commit_r": json_rate(sc["commit_r"]),
        "ceiling30": json_money(sc["ceiling30"]),
        "filter30_ok": sc["filter30_ok"],
    }
    return {
        "disclaimer": "educational",
        "totals": {
            "payoff": json_money(total),
            "count": len(ordered),
            "priority_one": hot,
        },
        "debts": [serialize_debt(d) for d in ordered],
        "offers": [serialize_offer(o, sc, ordered) for o in offers],
        "cash": {
            "income": json_money(cash.income),
            "variable_income": json_money(cash.variable_income),
            "essential": json_money(cash.essential),
            "discretionary": json_money(cash.discretionary),
            "reserve": json_money(cash.reserve),
            "shock": json_money(cash.shock),
        },
        "scenarios": serialized_sc,
        "cashflow": cashflow_months(cash, sc),
        "paths": paths(ordered, sc),
        "gates": gates(ordered, offers, sc, step_map),
        "steps": step_map,
        "alerts": list(ALERT_KEYS),
        "bank_script_facts": bank_script_facts(ordered),
        "avalanche": avalanche(ordered, ZERO, ZERO),
    }


EXAMPLE_DEBTS = (
    {
        "creditor": "Santander",
        "product": "rotativo",
        "payoff": "12000.00",
        "rate": "14",
        "installment": "360.00",
        "delinquency_status": "atraso",
        "dpd": 90,
        "notes": "largest arrears — priority 1",
    },
    {
        "creditor": "Inter",
        "product": "rotativo",
        "payoff": "8000.00",
        "rate": "13",
        "installment": "240.00",
        "delinquency_status": "atraso",
        "dpd": 45,
        "notes": "45 days past due",
    },
    {
        "creditor": "Nubank",
        "product": "rotativo",
        "payoff": "15000.00",
        "rate": "12",
        "installment": "450.00",
        "delinquency_status": "em_dia",
        "dpd": 0,
        "notes": "current, high rate",
    },
    {
        "creditor": "Banco Pan",
        "product": "cheque",
        "payoff": "5000.00",
        "rate": "8",
        "installment": "400.00",
        "delinquency_status": "atraso",
        "dpd": 15,
        "notes": "overdraft",
    },
    {
        "creditor": "Personal loan",
        "product": "emprestimo",
        "payoff": "20000.00",
        "rate": "6",
        "installment": "800.00",
        "term": 24,
        "delinquency_status": "em_dia",
        "dpd": 0,
        "notes": "not the first target",
    },
)

EXAMPLE_CASH = {
    "income": "12000.00",
    "variable_income": "0",
    "essential": "6000.00",
    "discretionary": "0",
    "reserve": "0",
    "shock": "1500.00",
}
