from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.periods import quarter_containing
from tests.factories import demo_expenses, demo_invoices, make_expense, make_invoice

AS_OF = date(2026, 11, 15)
Q4 = quarter_containing(AS_OF)


def test_seed_forecast_on_15_november() -> None:
    result = forecast_vat(Q4, AS_OF, demo_invoices(), demo_expenses())

    assert result.method == "expected_payment_dates"
    assert result.expected_additional_vat == Decimal("1520.00")
    assert result.estimated_vat_due == Decimal("4085.00")


def test_payments_after_as_of_are_not_known_yet() -> None:
    """Fed the true payment dates, the forecast still only sees what was known on 15 Nov."""
    invoices = demo_invoices(use_true_payment_dates=True)

    so_far = vat_so_far(Q4, AS_OF, invoices, demo_expenses())
    result = forecast_vat(Q4, AS_OF, invoices, demo_expenses())

    assert so_far.vat_due == Decimal("2565.00")
    assert result.estimated_vat_due == Decimal("4085.00")


def test_expense_after_as_of_is_not_known_yet() -> None:
    later_expense = make_expense(date(2026, 12, 1), "1190.00", "190.00")

    result = forecast_vat(Q4, AS_OF, demo_invoices(), [*demo_expenses(), later_expense])

    assert result.estimated_vat_due == Decimal("4085.00")


def test_open_invoice_expected_next_quarter_adds_nothing() -> None:
    open_next_quarter = make_invoice("2000.00", date(2026, 11, 10), expected=date(2027, 1, 15))

    result = forecast_vat(Q4, AS_OF, [open_next_quarter], [])

    assert result.expected_additional_vat == Decimal("0.00")
    assert result.estimated_vat_due == Decimal("0.00")


def test_open_invoice_without_expected_date_adds_nothing() -> None:
    unknown = make_invoice("8000.00", date(2026, 11, 1))

    result = forecast_vat(Q4, AS_OF, [unknown], [])

    assert result.expected_additional_vat == Decimal("0.00")


def test_expected_date_on_period_end_is_excluded() -> None:
    on_end = make_invoice("100.00", date(2026, 12, 1), expected=date(2027, 1, 1))

    result = forecast_vat(Q4, AS_OF, [on_end], [])

    assert result.expected_additional_vat == Decimal("0.00")


def test_paid_invoice_is_not_counted_twice() -> None:
    paid = make_invoice(
        "10000.00", date(2026, 10, 1), paid=date(2026, 10, 5), expected=date(2026, 10, 5)
    )

    result = forecast_vat(Q4, AS_OF, [paid], [])

    assert result.expected_additional_vat == Decimal("0.00")
    assert result.estimated_vat_due == Decimal("1900.00")


def test_overdue_open_invoice_still_counts() -> None:
    overdue = make_invoice("1000.00", date(2026, 10, 1), expected=date(2026, 11, 1))

    result = forecast_vat(Q4, AS_OF, [overdue], [])

    assert result.expected_additional_vat == Decimal("190.00")
    assert result.estimated_vat_due == Decimal("190.00")


def test_estimate_uses_net_vat_before_flooring() -> None:
    """Input VAT already recorded reduces the estimate, even when vat_due is 0."""
    open_invoice = make_invoice("8000.00", date(2026, 11, 1), expected=date(2026, 11, 30))
    larger_expense = make_expense(date(2026, 10, 10), "2000.00", "285.00")

    result = forecast_vat(Q4, AS_OF, [open_invoice], [larger_expense])

    assert result.expected_additional_vat == Decimal("1520.00")
    assert result.estimated_vat_due == Decimal("1235.00")


def test_as_of_outside_the_quarter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        forecast_vat(Q4, date(2027, 1, 1), [], [])
