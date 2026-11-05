import argparse
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.db.orm import Account, Expense, Invoice, Proposal, Transfer, User
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


def reset(session: Session) -> UUID:
    """Delete the demo account with its proposals and transfers, then seed it again."""
    account_id = demo_data.DEMO_ACCOUNT_ID
    proposal_ids = select(Proposal.id).where(Proposal.account_id == account_id)
    session.execute(delete(Transfer).where(Transfer.proposal_id.in_(proposal_ids)))
    session.execute(delete(Proposal).where(Proposal.account_id == account_id))
    session.execute(delete(Invoice).where(Invoice.account_id == account_id))
    session.execute(delete(Expense).where(Expense.account_id == account_id))
    session.execute(delete(Account).where(Account.id == account_id))
    session.execute(delete(User).where(User.id == demo_data.DEMO_USER_ID))
    session.expunge_all()
    return seed(session)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the demo books.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the demo account, its proposals and transfers, and start over",
    )
    args = parser.parse_args()
    with SessionLocal() as session, session.begin():
        account_id = reset(session) if args.reset else seed(session)
    print(f"account_id {account_id}")


if __name__ == "__main__":
    main()
