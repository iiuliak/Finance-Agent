import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from finance_agent.agent.intent import wants_transfer
from finance_agent.agent.when import View, mentions_when, quarter_label, view_for
from finance_agent.domain.forecast import forecast_vat, known_as_of
from finance_agent.domain.money import format_euros
from finance_agent.domain.periods import format_day, quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.domain.vat import calculate_vat
from finance_agent.models import ExpenseRead, InvoiceRead, VATProposalRead
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.services.proposals import draft_proposal, generate_proposal

# The same words the tools answer, including the German ones the transfer path already accepts.
_INVOICE_WORDS = (
    "invoice",
    "invoices",
    "rechnung",
    "rechnungen",
    "unpaid",
    "outstanding",
    "unbezahlt",
)
_EXPENSE_WORDS = ("expense", "expenses", "spent", "spend", "ausgabe", "ausgaben")
_VAT_WORDS = (
    "vat",
    "owe",
    "owed",
    "due",
    "tax",
    "forecast",
    "estimate",
    "umsatzsteuer",
    "mehrwertsteuer",
    "schulde",
    "schuldig",
)
_BALANCE_WORDS = ("balance", "operating", "cash", "reserve", "rücklage", "ruecklage")
_PAID_WORDS = ("paid", "payment", "bezahlt", "bezahlte")
_UNPAID_WORDS = ("unpaid", "outstanding", "unbezahlt")
_SUBJECTS = tuple(
    dict.fromkeys((*_INVOICE_WORDS, *_EXPENSE_WORDS, *_VAT_WORDS, *_BALANCE_WORDS, *_PAID_WORDS))
)


def answer(
    session: Session,
    account_id: UUID,
    message: str,
    history: Sequence[tuple[str, str]] = (),
) -> tuple[str, VATProposalRead | None]:
    """Answer from the books. A proposal is prepared only when the message asks for one."""
    if wants_transfer(message, history):
        draft = draft_proposal(session, account_id)
        if draft.proposed_amount == 0:
            return draft.explanation, None
        proposal = generate_proposal(session, account_id)
        return proposal.explanation, proposal

    question = focus_message(message, history)
    snapshot = get_snapshot(session, account_id)
    today = snapshot.account.as_of_date
    invoice_view = view_for(question, today, "invoice")
    expense_view = view_for(question, today, "expense")
    vat_view = view_for(question, today, "vat")
    account = snapshot.account
    asked_vat = _asks(question, *_VAT_WORDS)
    asked_invoices = _asks(question, *_INVOICE_WORDS) or (
        _asks(question, *_PAID_WORDS) and not asked_vat
    )
    asked_expenses = _asks(question, *_EXPENSE_WORDS)
    asked_balance = _asks(question, *_BALANCE_WORDS)

    parts: list[str] = []
    if asked_balance:
        parts.append(
            f"The operating account holds {format_euros(account.operating_balance)}. "
            f"The reserve holds {format_euros(account.reserve_balance)}."
        )
    if asked_invoices:
        visible, _expenses = known_as_of(invoice_view.list_as_of, snapshot.invoices, snapshot.expenses)
        parts.append(invoice_lines(_chosen_invoices(visible, invoice_view, question), invoice_view.label))
    if asked_expenses:
        _invoices, visible_expenses = known_as_of(expense_view.list_as_of, snapshot.invoices, snapshot.expenses)
        parts.append(expense_lines(_chosen_expenses(visible_expenses, expense_view), expense_view.label))
    if asked_vat:
        parts.append(
            explain_vat(
                vat_view,
                today,
                snapshot.invoices,
                snapshot.expenses,
                account.reserve_balance,
                account.operating_balance,
            )
        )
    if not parts:
        period = quarter_containing(today)
        visible_invoices, visible_expenses = known_as_of(today, snapshot.invoices, snapshot.expenses)
        so_far = calculate_vat(period, visible_invoices, visible_expenses)
        forecast = forecast_vat(period, today, snapshot.invoices, snapshot.expenses)
        parts.append(
            f"As of {format_day(today)}, the operating account holds {format_euros(account.operating_balance)} "
            f"and the reserve holds {format_euros(account.reserve_balance)}. "
            f"VAT already due this quarter is {format_euros(so_far.vat_due)}. "
            f"Estimated VAT at quarter end is {format_euros(forecast.estimated_vat_due)}. "
            "You can ask about invoices, expenses, VAT, or the reserve, "
            "or name a month, a quarter, or a day."
        )
    return "\n\n".join(parts), None


def reports_books(message: str, history: Sequence[tuple[str, str]] = ()) -> bool:
    """True when the reply should be the books, not a sentence the model composed."""
    return _asks(focus_message(message, history), *_SUBJECTS)


def focus_message(message: str, history: Sequence[tuple[str, str]]) -> str:
    """A follow-up that only names a period keeps the subject of the previous question."""
    if _asks(message, *_SUBJECTS) or not mentions_when(message):
        return message
    for role, earlier in reversed(history):
        if role == "user" and _asks(earlier, *_SUBJECTS):
            return f"{earlier}\n{message}"
    return message


def explain_vat(
    view: View,
    today: date,
    invoices: list[InvoiceRead],
    expenses: list[ExpenseRead],
    reserve_balance: Decimal,
    operating_balance: Decimal,
) -> str:
    """The VAT due on one day, and the invoices and expenses that produce it."""
    visible_invoices, visible_expenses = known_as_of(view.vat_as_of, invoices, expenses)
    so_far = calculate_vat(view.period, visible_invoices, visible_expenses)
    paid = [
        invoice
        for invoice in visible_invoices
        if invoice.payment_date is not None
        and view.period.period_start <= invoice.payment_date < view.period.period_end
    ]
    spent = [
        expense
        for expense in visible_expenses
        if view.period.period_start <= expense.expense_date < view.period.period_end
    ]
    quarter = quarter_label(view.period)
    filed_for_quarter = view.start == view.period.period_start and view.end == view.period.period_end
    if view.label and not filed_for_quarter and view.start is not None:
        opening = (
            f"VAT is filed for the quarter. As of {format_day(view.vat_as_of)}, "
            f"VAT due for {quarter} is **{format_euros(so_far.vat_due)}**."
        )
    else:
        opening = (
            f"As of {format_day(view.vat_as_of)}, VAT due for {quarter} is **{format_euros(so_far.vat_due)}**."
        )
    lines = [
        opening,
        "",
        f"Collected **{format_euros(so_far.collected_vat)}** from invoices paid in the quarter:",
    ]
    if paid:
        lines.extend(
            f"{format_euros(invoice.vat_amount)} from the {format_euros(invoice.net_amount)} "
            f"invoice issued {format_day(invoice.issue_date)}, paid on {format_day(invoice.payment_date)}"
            for invoice in sorted(paid, key=lambda invoice: invoice.payment_date or invoice.issue_date)
        )
    else:
        lines.append("No invoice was paid in this quarter by that day.")
    lines.extend(["", f"Input VAT **{format_euros(so_far.input_vat)}** from expenses in the quarter:"])
    if spent:
        lines.extend(
            f"{format_euros(expense.input_vat_amount)} on {format_day(expense.expense_date)}"
            for expense in sorted(spent, key=lambda expense: expense.expense_date)
        )
    else:
        lines.append("No expenses in this quarter by that day.")
    lines.extend(
        [
            "",
            f"{format_euros(so_far.collected_vat)} collected − {format_euros(so_far.input_vat)} "
            f"input VAT = {format_euros(so_far.net_vat)}.",
        ]
    )
    if so_far.net_vat < 0:
        lines.append("Input VAT is higher, so nothing is due.")
    elif so_far.vat_due > 0:
        lines.append("This VAT is still owed. Paying the Finanzamt is separate from the reserve.")
    current = view.period.period_start <= today < view.period.period_end and view.vat_as_of == today
    if current:
        forecast = forecast_vat(view.period, today, invoices, expenses)
        lines.extend(
            [
                "",
                f"Open invoices still expected this quarter add {format_euros(forecast.expected_additional_vat)}. "
                + _reserve_status(
                    reserve_balance,
                    operating_balance,
                    forecast.estimated_vat_due,
                ),
            ]
        )
    elif view.vat_as_of != today:
        lines.extend(
            [
                "",
                f"The reserve on the books today is {format_euros(reserve_balance)}, "
                f"and the operating account holds {format_euros(operating_balance)}. "
                "Those balances are the ones on the books today.",
            ]
        )
    return "\n".join(lines)


def _chosen_invoices(invoices: list[InvoiceRead], view: View, message: str) -> list[InvoiceRead]:
    chosen = invoices
    if view.start is not None and view.end is not None:
        if _asks(message, *_PAID_WORDS) and not _asks(message, *_UNPAID_WORDS):
            chosen = [
                invoice
                for invoice in invoices
                if invoice.payment_date is not None and view.start <= invoice.payment_date < view.end
            ]
        else:
            chosen = [
                invoice for invoice in invoices if view.start <= invoice.issue_date < view.end
            ]
    if _asks(message, *_UNPAID_WORDS):
        chosen = [invoice for invoice in chosen if invoice.payment_date is None]
    return sorted(chosen, key=lambda invoice: (invoice.issue_date, invoice.net_amount))


def _chosen_expenses(expenses: list[ExpenseRead], view: View) -> list[ExpenseRead]:
    chosen = expenses
    if view.start is not None and view.end is not None:
        chosen = [expense for expense in expenses if view.start <= expense.expense_date < view.end]
    return sorted(chosen, key=lambda expense: (expense.expense_date, expense.gross_amount))


def _reserve_status(
    reserve_balance: Decimal,
    operating_balance: Decimal,
    estimated_vat_due: Decimal,
) -> str:
    """Whether the reserve covers the estimate, and the transfer the tool would suggest."""
    if reserve_balance >= estimated_vat_due:
        return (
            f"Your reserve holds {format_euros(reserve_balance)}, which already covers the "
            f"estimated {format_euros(estimated_vat_due)} at quarter end."
        )
    gap = (
        f"Your reserve holds {format_euros(reserve_balance)}, less than the estimated "
        f"{format_euros(estimated_vat_due)} at quarter end. "
    )
    amount = proposed_reserve_transfer(estimated_vat_due, operating_balance, reserve_balance)
    if amount == 0:
        return gap + "The operating account has nothing left to move."
    return (
        gap
        + f"Moving {format_euros(amount)} from the operating account would add it to the reserve. "
        "Shall I set it aside?"
    )


def _asks(message: str, *words: str) -> bool:
    text = message.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def invoice_lines(invoices: list[InvoiceRead], label: str | None = None) -> str:
    """One record per line. Dates are written out so a year is hard to mistype."""
    scope = f" in {label}" if label else ""
    if not invoices:
        return f"No invoices{scope}."
    lines = []
    for invoice in invoices:
        if invoice.payment_date is None:
            expected = (
                f", expected {format_day(invoice.expected_payment_date)}"
                if invoice.expected_payment_date is not None
                else ""
            )
            state = f"unpaid{expected}"
        else:
            state = f"paid on {format_day(invoice.payment_date)}"
        lines.append(
            f"{format_euros(invoice.net_amount)} net, VAT {format_euros(invoice.vat_amount)}, "
            f"issued {format_day(invoice.issue_date)}, {state}"
        )
    heading = f"**Invoices{scope}**"
    return heading + "\n" + "\n".join(lines)


def expense_lines(expenses: list[ExpenseRead], label: str | None = None) -> str:
    scope = f" in {label}" if label else ""
    if not expenses:
        return f"No expenses{scope}."
    lines = [
        f"{format_day(expense.expense_date)}: {format_euros(expense.gross_amount)} gross, "
        f"input VAT {format_euros(expense.input_vat_amount)}"
        for expense in expenses
    ]
    return f"**Expenses{scope}**\n" + "\n".join(lines)
