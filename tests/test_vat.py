from datetime import date
from decimal import Decimal

import pytest

from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.vat import calculate_vat
from tests.factories import demo_expenses, demo_invoices, make_expense, make_invoice

Q4 = quarter_containing(date(2026, 11, 15))


@pytest.mark.parametrize(
    ("as_of", "start", "end"),
    [
        (date(2026, 10, 1), date(2026, 10, 1), date(2027, 1, 1)),
        (date(2026, 11, 15), date(2026, 10, 1), date(2027, 1, 1)),
        (date(2026, 12, 31), date(2026, 10, 1), date(2027, 1, 1)),
        (date(2027, 1, 1), date(2027, 1, 1), date(2027, 4, 1)),
        (date(2026, 3, 31), date(2026, 1, 1), date(2026, 4, 1)),
        (date(2026, 4, 1), date(2026, 4, 1), date(2026, 7, 1)),
        (date(2026, 7, 1), date(2026, 7, 1), date(2026, 10, 1)),
    ],
)
def test_quarter_containing(as_of: date, start: date, end: date) -> None:
    period = quarter_containing(as_of)
    assert period.period_start == start
    assert period.period_end == end


def test_seed_vat_already_due() -> None:
    result = calculate_vat(Q4, demo_invoices(), demo_expenses())

    assert result.collected_vat == Decimal("2850.00")
    assert result.input_vat == Decimal("285.00")
    assert result.net_vat == Decimal("2565.00")
    assert result.vat_due == Decimal("2565.00")


def test_payment_on_period_end_is_excluded() -> None:
    paid_inside = make_invoice("100.00", date(2026, 10, 1), paid=date(2026, 10, 1))
    paid_on_end = make_invoice("100.00", date(2026, 12, 1), paid=date(2027, 1, 1))

    result = calculate_vat(Q4, [paid_inside, paid_on_end], [])

    assert result.collected_vat == Decimal("19.00")
    assert result.vat_due == Decimal("19.00")


def test_unpaid_invoice_adds_nothing() -> None:
    open_invoice = make_invoice("8000.00", date(2026, 11, 1))

    result = calculate_vat(Q4, [open_invoice], [])

    assert result.collected_vat == Decimal("0.00")
    assert result.vat_due == Decimal("0.00")


def test_expense_on_period_boundaries() -> None:
    on_start = make_expense(date(2026, 10, 1), "119.00", "19.00")
    on_end = make_expense(date(2027, 1, 1), "119.00", "19.00")

    result = calculate_vat(Q4, [], [on_start, on_end])

    assert result.input_vat == Decimal("19.00")
    assert result.net_vat == Decimal("-19.00")
    assert result.vat_due == Decimal("0.00")


def test_input_vat_above_collected_vat_is_a_credit() -> None:
    paid = make_invoice("100.00", date(2026, 10, 2), paid=date(2026, 10, 3))
    larger_expense = make_expense(date(2026, 10, 4), "1000.00", "250.00")

    result = calculate_vat(Q4, [paid], [larger_expense])

    assert result.net_vat == Decimal("-231.00")
    assert result.vat_due == Decimal("0.00")
