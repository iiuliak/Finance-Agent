from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

DEMO_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
DEMO_ACCOUNT_ID = UUID("00000000-0000-4000-8000-000000000002")
DEMO_USER_NAME = "Demo Freelancer"

OPERATING_BALANCE = Decimal("12000.00")
RESERVE_BALANCE = Decimal("500.00")
VAT_RATE = Decimal("0.1900")


@dataclass(frozen=True)
class DemoInvoice:
    id: UUID
    net_amount: Decimal
    issue_date: date
    payment_date: date | None  # the real payment date; a later day is hidden until as_of reaches it
    expected_payment_date: date | None


@dataclass(frozen=True)
class DemoExpense:
    id: UUID
    expense_date: date
    gross_amount: Decimal
    input_vat_amount: Decimal


@dataclass(frozen=True)
class _QuarterBooks:
    """Four invoices and two expenses, at the same offsets in every quarter."""

    invoice_ids: tuple[str, str, str, str]
    expense_ids: tuple[str, str]
    nets: tuple[str, str, str, str]


# Same shape each quarter, different amounts, so the list covers the year
# and the quarter you are standing in still has a forecast to make.
# Offsets from the quarter start: paid on day 4 and day 32, a slip expected
# on day 60 and paid 4 days after the quarter, an early payment on day 70
# whose expected day is 14 days after the quarter.
_QUARTERS = (
    _QuarterBooks(
        ("000000000111", "000000000112", "000000000113", "000000000114"),
        ("000000000211", "000000000212"),
        ("6000.00", "3000.00", "4000.00", "1000.00"),
    ),
    _QuarterBooks(
        ("000000000121", "000000000122", "000000000123", "000000000124"),
        ("000000000221", "000000000222"),
        ("7000.00", "9000.00", "11000.00", "1500.00"),
    ),
    _QuarterBooks(
        ("000000000131", "000000000132", "000000000133", "000000000134"),
        ("000000000231", "000000000232"),
        ("12000.00", "2500.00", "6500.00", "8500.00"),
    ),
    _QuarterBooks(
        ("000000000101", "000000000102", "000000000103", "000000000104"),
        ("000000000201", "000000000202"),
        ("10000.00", "5000.00", "8000.00", "2000.00"),
    ),
)


def invoices_for(as_of: date) -> tuple[DemoInvoice, ...]:
    """One year's invoices. The year is the year of as_of; the dates do not slide."""
    invoices: list[DemoInvoice] = []
    for (start, end), quarter in zip(_quarter_bounds(as_of.year), _QUARTERS, strict=True):
        paid_early = start + timedelta(days=4)
        paid_recent = start + timedelta(days=32)
        # The summer invoice that slips is paid in January. An October payment
        # would land in the fourth quarter and change that quarter's bill.
        slip_paid = date(end.year + 1, 1, 20) if start.month == 7 else end + timedelta(days=4)
        invoices.extend(
            (
                DemoInvoice(
                    id=_uuid(quarter.invoice_ids[0]),
                    net_amount=Decimal(quarter.nets[0]),
                    issue_date=start,
                    payment_date=paid_early,
                    expected_payment_date=paid_early,
                ),
                DemoInvoice(
                    id=_uuid(quarter.invoice_ids[1]),
                    net_amount=Decimal(quarter.nets[1]),
                    issue_date=start + timedelta(days=19),
                    payment_date=paid_recent,
                    expected_payment_date=paid_recent,
                ),
                DemoInvoice(
                    id=_uuid(quarter.invoice_ids[2]),
                    net_amount=Decimal(quarter.nets[2]),
                    issue_date=start + timedelta(days=31),
                    payment_date=slip_paid,
                    expected_payment_date=start + timedelta(days=60),
                ),
                DemoInvoice(
                    id=_uuid(quarter.invoice_ids[3]),
                    net_amount=Decimal(quarter.nets[3]),
                    issue_date=start + timedelta(days=40),
                    payment_date=start + timedelta(days=70),
                    expected_payment_date=end + timedelta(days=14),
                ),
            )
        )
    return tuple(invoices)


def expenses_for(as_of: date) -> tuple[DemoExpense, ...]:
    """Two expenses in every quarter of as_of's year, on day 9 and day 31."""
    expenses: list[DemoExpense] = []
    for (start, _end), quarter in zip(_quarter_bounds(as_of.year), _QUARTERS, strict=True):
        expenses.extend(
            (
                DemoExpense(
                    id=_uuid(quarter.expense_ids[0]),
                    expense_date=start + timedelta(days=9),
                    gross_amount=Decimal("1190.00"),
                    input_vat_amount=Decimal("190.00"),
                ),
                DemoExpense(
                    id=_uuid(quarter.expense_ids[1]),
                    expense_date=start + timedelta(days=31),
                    gross_amount=Decimal("595.00"),
                    input_vat_amount=Decimal("95.00"),
                ),
            )
        )
    return tuple(expenses)


def _quarter_bounds(year: int) -> tuple[tuple[date, date], ...]:
    starts = (date(year, 1, 1), date(year, 4, 1), date(year, 7, 1), date(year, 10, 1))
    ends = (date(year, 4, 1), date(year, 7, 1), date(year, 10, 1), date(year + 1, 1, 1))
    return tuple(zip(starts, ends, strict=True))


def _uuid(suffix: str) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{suffix}")
