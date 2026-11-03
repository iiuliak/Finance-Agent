from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ExplanationFacts:
    """Figures already computed in Python. The wording must not change them."""

    collected_vat: Decimal
    input_vat: Decimal
    additional_vat: Decimal
    reserve_balance: Decimal
    estimated_vat_due: Decimal
    proposed_amount: Decimal


def _euros(amount: Decimal) -> str:
    return f"€{amount:,.2f}"


def write_explanation(facts: ExplanationFacts) -> str:
    """Plain-language proposal. Every amount is copied from facts."""
    return (
        f"This quarter you have collected {_euros(facts.collected_vat)} in VAT "
        f"and recorded {_euros(facts.input_vat)} of input VAT. "
        f"Invoices still expected to be paid this quarter add {_euros(facts.additional_vat)}. "
        f"Your reserve holds {_euros(facts.reserve_balance)}. "
        f"Estimated VAT at quarter end is {_euros(facts.estimated_vat_due)}. "
        f"Move {_euros(facts.proposed_amount)} from your operating account into the reserve."
    )
