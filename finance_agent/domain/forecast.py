from datetime import date

from finance_agent.domain.money import ZERO, money
from finance_agent.domain.vat import calculate_vat
from finance_agent.models import (
    ExpenseRead,
    InvoiceRead,
    VATCalculation,
    VATForecast,
    VATPeriod,
)


def known_as_of(
    as_of: date,
    invoices: list[InvoiceRead],
    expenses: list[ExpenseRead],
) -> tuple[list[InvoiceRead], list[ExpenseRead]]:
    """The books as they looked on as_of: later payments and expenses are not known yet."""
    visible_invoices = [
        invoice
        if invoice.payment_date is None or invoice.payment_date <= as_of
        else invoice.model_copy(update={"payment_date": None})
        for invoice in invoices
    ]
    visible_expenses = [expense for expense in expenses if expense.expense_date <= as_of]
    return visible_invoices, visible_expenses


def vat_so_far(
    period: VATPeriod,
    as_of: date,
    invoices: list[InvoiceRead],
    expenses: list[ExpenseRead],
) -> VATCalculation:
    visible_invoices, visible_expenses = known_as_of(as_of, invoices, expenses)
    return calculate_vat(period, visible_invoices, visible_expenses)


def forecast_vat(
    period: VATPeriod,
    as_of: date,
    invoices: list[InvoiceRead],
    expenses: list[ExpenseRead],
) -> VATForecast:
    """Estimate quarter-end VAT from invoices still expected to be paid."""
    visible_invoices, visible_expenses = known_as_of(as_of, invoices, expenses)
    so_far = calculate_vat(period, visible_invoices, visible_expenses)

    additional = ZERO
    for invoice in visible_invoices:
        expected_on = invoice.expected_payment_date
        if (
            invoice.payment_date is None
            and expected_on is not None
            and period.period_start <= expected_on < period.period_end
        ):
            additional += invoice.vat_amount

    additional = money(additional)
    return VATForecast(
        period_start=period.period_start,
        period_end=period.period_end,
        as_of=as_of,
        method="expected_payment_dates",
        expected_additional_vat=additional,
        estimated_vat_due=max(so_far.net_vat + additional, ZERO),
    )
