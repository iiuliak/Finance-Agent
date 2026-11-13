from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from finance_agent.db.orm import Expense, Invoice
from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.money import money
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.models import BooksRead, ExpenseCreate, InvoiceCreate
from finance_agent.repositories.ledger import (
    get_snapshot,
    lock_account,
    supersede_pending_proposals,
)

_RATE_PLACES = Decimal("0.0001")


def describe_books(session: Session, account_id: UUID) -> BooksRead:
    """The stored ledger, and the VAT figures the account's day produces."""
    snapshot = get_snapshot(session, account_id)
    as_of = snapshot.account.as_of_date
    period = quarter_containing(as_of)
    so_far = vat_so_far(period, as_of, snapshot.invoices, snapshot.expenses)
    forecast = forecast_vat(period, as_of, snapshot.invoices, snapshot.expenses)
    proposed = proposed_reserve_transfer(
        forecast.estimated_vat_due,
        snapshot.account.operating_balance,
        snapshot.account.reserve_balance,
    )
    return BooksRead(
        as_of=as_of,
        operating_balance=snapshot.account.operating_balance,
        reserve_balance=snapshot.account.reserve_balance,
        vat_due=so_far.vat_due,
        expected_additional_vat=forecast.expected_additional_vat,
        forecast_vat=forecast.estimated_vat_due,
        proposed_amount=proposed,
        invoices=snapshot.invoices,
        expenses=snapshot.expenses,
    )


def set_as_of(session: Session, account_id: UUID, as_of: date) -> BooksRead:
    """Move the day the agent reads. A pending card was computed for the old day."""
    account = lock_account(session, account_id)
    if account.as_of_date != as_of:
        account.as_of_date = as_of
        supersede_pending_proposals(session, account_id)
        session.flush()
    return describe_books(session, account_id)


def set_balances(
    session: Session,
    account_id: UUID,
    operating_balance: Decimal,
    reserve_balance: Decimal,
) -> BooksRead:
    account = lock_account(session, account_id)
    operating_balance = money(operating_balance)
    reserve_balance = money(reserve_balance)
    if (
        account.operating_balance != operating_balance
        or account.reserve_balance != reserve_balance
    ):
        account.operating_balance = operating_balance
        account.reserve_balance = reserve_balance
        supersede_pending_proposals(session, account_id)
        session.flush()
    return describe_books(session, account_id)


def add_invoice(session: Session, account_id: UUID, invoice: InvoiceCreate) -> BooksRead:
    lock_account(session, account_id)
    session.add(
        Invoice(
            account_id=account_id,
            net_amount=money(invoice.net_amount),
            vat_rate=invoice.vat_rate.quantize(_RATE_PLACES),
            issue_date=invoice.issue_date,
            payment_date=invoice.payment_date,
            expected_payment_date=invoice.expected_payment_date,
        )
    )
    supersede_pending_proposals(session, account_id)
    session.flush()
    return describe_books(session, account_id)


def delete_invoice(session: Session, account_id: UUID, invoice_id: UUID) -> BooksRead:
    lock_account(session, account_id)
    row = session.get(Invoice, invoice_id)
    if row is None or row.account_id != account_id:
        raise LookupError(f"Invoice {invoice_id} not found")
    session.delete(row)
    supersede_pending_proposals(session, account_id)
    session.flush()
    return describe_books(session, account_id)


def add_expense(session: Session, account_id: UUID, expense: ExpenseCreate) -> BooksRead:
    lock_account(session, account_id)
    session.add(
        Expense(
            account_id=account_id,
            expense_date=expense.expense_date,
            gross_amount=money(expense.gross_amount),
            input_vat_amount=money(expense.input_vat_amount),
        )
    )
    supersede_pending_proposals(session, account_id)
    session.flush()
    return describe_books(session, account_id)


def delete_expense(session: Session, account_id: UUID, expense_id: UUID) -> BooksRead:
    lock_account(session, account_id)
    row = session.get(Expense, expense_id)
    if row is None or row.account_id != account_id:
        raise LookupError(f"Expense {expense_id} not found")
    session.delete(row)
    supersede_pending_proposals(session, account_id)
    session.flush()
    return describe_books(session, account_id)
