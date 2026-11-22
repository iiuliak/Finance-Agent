from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from finance_agent.db.orm import Account, Expense, Invoice, User
from finance_agent.models import ProposalStatus, VATProposalDraft
from finance_agent.repositories.ledger import get_proposal, get_snapshot, insert_proposal


def _account(session: Session) -> Account:
    user = User(id=uuid4(), name="Test Freelancer")
    session.add(user)
    session.flush()
    account = Account(
        id=uuid4(),
        user_id=user.id,
        operating_balance=Decimal("12000.00"),
        reserve_balance=Decimal("500.00"),
    )
    session.add(account)
    session.flush()
    return account


def test_invoice_vat_amount_comes_from_the_database(db_session: Session) -> None:
    account = _account(db_session)
    db_session.add_all(
        [
            Invoice(
                account_id=account.id,
                net_amount=Decimal("100.00"),
                vat_rate=Decimal("0.1900"),
                issue_date=date(2026, 10, 1),
            ),
            Expense(
                account_id=account.id,
                expense_date=date(2026, 10, 10),
                gross_amount=Decimal("1190.00"),
                input_vat_amount=Decimal("190.00"),
            ),
        ]
    )
    db_session.flush()

    snapshot = get_snapshot(db_session, account.id)

    assert snapshot.invoices[0].vat_amount == Decimal("19.00")
    assert snapshot.expenses[0].input_vat_amount == Decimal("190.00")
    assert snapshot.account.operating_balance == Decimal("12000.00")


def test_insert_proposal_starts_pending(db_session: Session) -> None:
    account = _account(db_session)
    draft = VATProposalDraft(
        account_id=account.id,
        period_start=date(2026, 10, 1),
        period_end=date(2027, 1, 1),
        vat_due=Decimal("2565.00"),
        forecast_vat=Decimal("4085.00"),
        proposed_amount=Decimal("3585.00"),
        explanation="Move €3,585 to your tax reserve.",
    )

    created = insert_proposal(db_session, draft)
    found = get_proposal(db_session, created.id)

    assert created.status == ProposalStatus.PENDING
    assert found.proposed_amount == Decimal("3585.00")
    assert found.approved_by is None
