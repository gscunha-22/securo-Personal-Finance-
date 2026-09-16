"""Account-type helpers shared by sync, balances and reports."""

LIABILITY_ACCOUNT_TYPES = frozenset({"credit_card", "loan"})


def is_liability_type(account_type: str | None) -> bool:
    """True when the account's outstanding balance reduces net worth."""
    return (account_type or "") in LIABILITY_ACCOUNT_TYPES
