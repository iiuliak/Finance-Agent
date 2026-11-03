from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from finance_agent import demo_data
from finance_agent.domain.money import money
from finance_agent.models import ExpenseRead, InvoiceRead

ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")


def make_invoice(
    net: str,
    issued: date,
    paid: date | None = None,
    expected: date | None = None,
    rate: str = "0.1900",
) -> InvoiceRead:
    net_amount = Decimal(net)
    vat_rate = Decimal(rate)
    return InvoiceRead(
        id=uuid4(),
        account_id=ACCOUNT_ID,
        net_amount=net_amount,
        vat_rate=vat_rate,
        vat_amount=money(net_amount * vat_rate),  # stands in for the generated column
        issue_date=issued,
        payment_date=paid,
        expected_payment_date=expected,
    )


def make_expense(on: date, gross: str, input_vat: str) -> ExpenseRead:
    return ExpenseRead(
        id=uuid4(),
        account_id=ACCOUNT_ID,
        expense_date=on,
        gross_amount=Decimal(gross),
        input_vat_amount=Decimal(input_vat),
    )


def demo_invoices(use_true_payment_dates: bool = False) -> list[InvoiceRead]:
    return [
        make_invoice(
            str(invoice.net_amount),
            invoice.issue_date,
            paid=invoice.true_payment_date if use_true_payment_dates else invoice.payment_date,
            expected=invoice.expected_payment_date,
        )
        for invoice in demo_data.INVOICES
    ]


def demo_expenses() -> list[ExpenseRead]:
    return [
        make_expense(expense.expense_date, str(expense.gross_amount), str(expense.input_vat_amount))
        for expense in demo_data.EXPENSES
    ]
