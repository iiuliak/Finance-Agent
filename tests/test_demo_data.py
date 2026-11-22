from datetime import date
from decimal import Decimal

from finance_agent.demo_data import expenses_for, invoices_for
from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.domain.vat import calculate_vat
from finance_agent.eval_forecast import evaluate
from tests.factories import demo_expenses, demo_invoices

OPERATING = Decimal("12000.00")
RESERVE = Decimal("500.00")


def test_the_year_has_a_payment_in_every_month() -> None:
    invoices = invoices_for(date(2026, 11, 15))

    assert len(invoices) == 16
    assert len(expenses_for(date(2026, 11, 15))) == 8
    assert {invoice.payment_date.month for invoice in invoices if invoice.payment_date} == set(range(1, 13))


def test_15_november_2026_keeps_the_fourth_quarter_dates() -> None:
    invoices = [
        invoice for invoice in invoices_for(date(2026, 11, 15)) if invoice.issue_date >= date(2026, 10, 1)
    ]
    expenses = [
        expense for expense in expenses_for(date(2026, 11, 15)) if expense.expense_date >= date(2026, 10, 1)
    ]

    assert [(invoice.issue_date, invoice.payment_date, invoice.expected_payment_date) for invoice in invoices] == [
        (date(2026, 10, 1), date(2026, 10, 5), date(2026, 10, 5)),
        (date(2026, 10, 20), date(2026, 11, 2), date(2026, 11, 2)),
        (date(2026, 11, 1), date(2027, 1, 5), date(2026, 11, 30)),
        (date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 15)),
    ]
    assert [expense.expense_date for expense in expenses] == [date(2026, 10, 10), date(2026, 11, 1)]


def test_15_november_card_ignores_the_other_quarters() -> None:
    due, additional, estimate, proposed = _opening_card(date(2026, 11, 15))

    assert due == Decimal("2565.00")
    assert additional == Decimal("1520.00")
    assert estimate == Decimal("4085.00")
    assert proposed == Decimal("3585.00")
    result = evaluate(date(2026, 11, 15))
    assert result.true_vat_due == Decimal("2945.00")
    assert result.absolute_error == Decimal("1140.00")


def test_15_february_reads_the_first_quarter() -> None:
    """15 February is the same point in the first quarter as 15 November is in the fourth."""
    due, additional, estimate, proposed = _opening_card(date(2026, 2, 15))

    assert due == Decimal("1425.00")
    assert additional == Decimal("760.00")
    assert estimate == Decimal("2185.00")
    assert proposed == Decimal("1685.00")
    result = evaluate(date(2026, 2, 15))
    assert result.true_vat_due == Decimal("1615.00")
    assert result.absolute_error == Decimal("570.00")


def test_another_year_uses_that_year() -> None:
    invoices = invoices_for(date(2027, 11, 15))

    assert any(invoice.issue_date == date(2027, 10, 1) for invoice in invoices)
    assert all(invoice.issue_date.year == 2027 for invoice in invoices)


def _opening_card(as_of: date) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    period = quarter_containing(as_of)
    invoices = demo_invoices(as_of)
    expenses = demo_expenses(as_of)
    so_far = vat_so_far(period, as_of, invoices, expenses)
    forecast = forecast_vat(period, as_of, invoices, expenses)
    true_vat = calculate_vat(period, invoices, expenses).vat_due
    assert true_vat == evaluate(as_of).true_vat_due
    proposed = proposed_reserve_transfer(forecast.estimated_vat_due, OPERATING, RESERVE)
    return (
        so_far.vat_due,
        forecast.expected_additional_vat,
        forecast.estimated_vat_due,
        proposed,
    )
