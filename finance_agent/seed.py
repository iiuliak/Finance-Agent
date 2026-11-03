from uuid import UUID

from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.db.orm import Account, Expense, Invoice, User
from finance_agent.db.session import SessionLocal


def seed(session: Session) -> UUID:
    """Insert the demo books once. A second call leaves the database as it is."""
    if session.get(Account, demo_data.DEMO_ACCOUNT_ID) is not None:
        return demo_data.DEMO_ACCOUNT_ID

    session.add(User(id=demo_data.DEMO_USER_ID, name=demo_data.DEMO_USER_NAME))
    session.flush()
    session.add(
        Account(
            id=demo_data.DEMO_ACCOUNT_ID,
            user_id=demo_data.DEMO_USER_ID,
            operating_balance=demo_data.OPERATING_BALANCE,
            reserve_balance=demo_data.RESERVE_BALANCE,
        )
    )
    session.flush()
    session.add_all(
        Invoice(
            id=invoice.id,
            account_id=demo_data.DEMO_ACCOUNT_ID,
            net_amount=invoice.net_amount,
            vat_rate=demo_data.VAT_RATE,
            issue_date=invoice.issue_date,
            payment_date=invoice.payment_date,
            expected_payment_date=invoice.expected_payment_date,
        )
        for invoice in demo_data.INVOICES
    )
    session.add_all(
        Expense(
            id=expense.id,
            account_id=demo_data.DEMO_ACCOUNT_ID,
            expense_date=expense.expense_date,
            gross_amount=expense.gross_amount,
            input_vat_amount=expense.input_vat_amount,
        )
        for expense in demo_data.EXPENSES
    )
    session.flush()
    return demo_data.DEMO_ACCOUNT_ID


def main() -> None:
    with SessionLocal() as session, session.begin():
        account_id = seed(session)
    print(f"account_id {account_id}")


if __name__ == "__main__":
    main()
