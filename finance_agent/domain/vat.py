from finance_agent.domain.money import ZERO, money
from finance_agent.models import ExpenseRead, InvoiceRead, VATCalculation, VATPeriod


def calculate_vat(
    period: VATPeriod,
    invoices: list[InvoiceRead],
    expenses: list[ExpenseRead],
) -> VATCalculation:
    """VAT for a quarter. Cash basis: only invoices paid inside the quarter count."""
    collected = ZERO
    for invoice in invoices:
        paid_on = invoice.payment_date
        if paid_on is not None and period.period_start <= paid_on < period.period_end:
            collected += invoice.vat_amount

    input_vat = ZERO
    for expense in expenses:
        if period.period_start <= expense.expense_date < period.period_end:
            input_vat += expense.input_vat_amount

    collected = money(collected)
    input_vat = money(input_vat)
    net_vat = money(collected - input_vat)
    return VATCalculation(
        period_start=period.period_start,
        period_end=period.period_end,
        collected_vat=collected,
        input_vat=input_vat,
        net_vat=net_vat,
        vat_due=max(net_vat, ZERO),
    )
