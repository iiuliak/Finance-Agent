from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_euros(amount: Decimal) -> str:
    return f"€{amount:,.2f}"
