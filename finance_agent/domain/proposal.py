from decimal import Decimal

from finance_agent.domain.money import ZERO, money


def proposed_reserve_transfer(
    estimated_vat_due: Decimal,
    operating_balance: Decimal,
    reserve_balance: Decimal,
) -> Decimal:
    """Cash to move into the reserve, capped by the operating balance."""
    shortfall = max(estimated_vat_due - reserve_balance, ZERO)
    return money(min(operating_balance, shortfall))
