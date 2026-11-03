import re
from uuid import UUID

from sqlalchemy.orm import Session

from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.money import format_euros
from finance_agent.domain.periods import quarter_containing
from finance_agent.models import VATProposalRead
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.services.proposals import generate_proposal
from finance_agent.settings import get_settings


def answer(session: Session, account_id: UUID, message: str) -> tuple[str, VATProposalRead | None]:
    """Answer from the books. A proposal is prepared only when the message asks for one."""
    if _asks(message, "move", "transfer", "aside", "proposal"):
        proposal = generate_proposal(session, account_id)
        return proposal.explanation, proposal

    snapshot = get_snapshot(session, account_id)
    as_of = get_settings().as_of_date
    period = quarter_containing(as_of)
    so_far = vat_so_far(period, as_of, snapshot.invoices, snapshot.expenses)
    forecast = forecast_vat(period, as_of, snapshot.invoices, snapshot.expenses)
    account = snapshot.account

    parts: list[str] = []
    if _asks(message, "balance", "operating", "cash", "reserve"):
        parts.append(
            f"The operating account holds {format_euros(account.operating_balance)}. "
            f"The reserve holds {format_euros(account.reserve_balance)}."
        )
    if _asks(message, "invoice", "invoices", "unpaid", "paid"):
        parts.append(_invoices(snapshot.invoices))
    if _asks(message, "expense", "expenses", "spent", "spend"):
        parts.append(_expenses(snapshot.expenses))
    if _asks(message, "forecast", "quarter", "estimate"):
        parts.append(
            f"Estimated VAT at quarter end is {format_euros(forecast.estimated_vat_due)}. "
            f"Open invoices still expected this quarter add {format_euros(forecast.expected_additional_vat)}."
        )
    if _asks(message, "vat", "owe", "due", "tax"):
        parts.append(
            f"VAT already due this quarter is {format_euros(so_far.vat_due)}. "
            f"That is {format_euros(so_far.collected_vat)} collected and "
            f"{format_euros(so_far.input_vat)} of input VAT."
        )
    if not parts:
        parts.append(
            f"The operating account holds {format_euros(account.operating_balance)} "
            f"and the reserve holds {format_euros(account.reserve_balance)}. "
            f"VAT already due this quarter is {format_euros(so_far.vat_due)}. "
            f"Estimated VAT at quarter end is {format_euros(forecast.estimated_vat_due)}. "
            "You can ask about invoices, expenses, or the reserve, "
            "or ask me to move money into the reserve."
        )
    return " ".join(parts), None


def _asks(message: str, *words: str) -> bool:
    text = message.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _invoices(invoices) -> str:
    lines = []
    for invoice in invoices:
        if invoice.payment_date is None:
            expected = (
                f", expected {invoice.expected_payment_date.isoformat()}"
                if invoice.expected_payment_date is not None
                else ""
            )
            state = f"unpaid{expected}"
        else:
            state = f"paid on {invoice.payment_date.isoformat()}"
        lines.append(
            f"{format_euros(invoice.net_amount)} net, VAT {format_euros(invoice.vat_amount)}, "
            f"issued {invoice.issue_date.isoformat()}, {state}"
        )
    return "Invoices: " + "; ".join(lines) + "."


def _expenses(expenses) -> str:
    lines = [
        f"{expense.expense_date.isoformat()}: {format_euros(expense.gross_amount)} gross, "
        f"input VAT {format_euros(expense.input_vat_amount)}"
        for expense in expenses
    ]
    return "Expenses: " + "; ".join(lines) + "."
