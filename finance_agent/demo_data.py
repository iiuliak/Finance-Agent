from dataclasses import dataclass
from datetime import date
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
    payment_date: date | None  # known on 15 Nov 2026; this is what the database stores
    expected_payment_date: date | None
    true_payment_date: date  # used only by the forecast evaluation


@dataclass(frozen=True)
class DemoExpense:
    id: UUID
    expense_date: date
    gross_amount: Decimal
    input_vat_amount: Decimal


INVOICES = (
    DemoInvoice(
        id=UUID("00000000-0000-4000-8000-000000000101"),
        net_amount=Decimal("10000.00"),
        issue_date=date(2026, 10, 1),
        payment_date=date(2026, 10, 5),
        expected_payment_date=date(2026, 10, 5),
        true_payment_date=date(2026, 10, 5),
    ),
    DemoInvoice(
        id=UUID("00000000-0000-4000-8000-000000000102"),
        net_amount=Decimal("5000.00"),
        issue_date=date(2026, 10, 20),
        payment_date=date(2026, 11, 2),
        expected_payment_date=date(2026, 11, 2),
        true_payment_date=date(2026, 11, 2),
    ),
    DemoInvoice(
        id=UUID("00000000-0000-4000-8000-000000000103"),
        net_amount=Decimal("8000.00"),
        issue_date=date(2026, 11, 1),
        payment_date=None,
        expected_payment_date=date(2026, 11, 30),
        true_payment_date=date(2027, 1, 5),
    ),
    DemoInvoice(
        id=UUID("00000000-0000-4000-8000-000000000104"),
        net_amount=Decimal("2000.00"),
        issue_date=date(2026, 11, 10),
        payment_date=None,
        expected_payment_date=date(2027, 1, 15),
        true_payment_date=date(2026, 12, 10),
    ),
)

EXPENSES = (
    DemoExpense(
        id=UUID("00000000-0000-4000-8000-000000000201"),
        expense_date=date(2026, 10, 10),
        gross_amount=Decimal("1190.00"),
        input_vat_amount=Decimal("190.00"),
    ),
    DemoExpense(
        id=UUID("00000000-0000-4000-8000-000000000202"),
        expense_date=date(2026, 11, 1),
        gross_amount=Decimal("595.00"),
        input_vat_amount=Decimal("95.00"),
    ),
)
