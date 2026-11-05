from dataclasses import dataclass
from decimal import Decimal

from finance_agent.domain.money import format_euros


@dataclass(frozen=True)
class ExplanationFacts:
    """Figures already computed in Python. The wording must not change them."""

    collected_vat: Decimal
    input_vat: Decimal
    additional_vat: Decimal
    reserve_balance: Decimal
    estimated_vat_due: Decimal
    proposed_amount: Decimal


def write_explanation(facts: ExplanationFacts) -> str:
    """Plain-language proposal. Every amount is copied from facts."""
    figures = (
        f"This quarter you have collected {format_euros(facts.collected_vat)} in VAT "
        f"and recorded {format_euros(facts.input_vat)} of input VAT. "
        f"Invoices still expected to be paid this quarter add {format_euros(facts.additional_vat)}. "
        f"Estimated VAT at quarter end is {format_euros(facts.estimated_vat_due)}. "
    )
    if facts.proposed_amount == 0:
        return figures + (
            f"Your reserve already holds {format_euros(facts.reserve_balance)}, "
            "which covers it. There is nothing to move."
        )
    return figures + (
        f"Your reserve holds {format_euros(facts.reserve_balance)}. "
        f"Move {format_euros(facts.proposed_amount)} from your operating account into the reserve."
    )
