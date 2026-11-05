from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.db.orm import Invoice, Proposal, Transfer, User
from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.models import Decision
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.seed import reset, seed
from finance_agent.services.proposals import generate_proposal
from finance_agent.services.transfers import decide
from finance_agent.settings import get_settings


def test_seed_matches_the_answer_key(db_session: Session) -> None:
    as_of = get_settings().as_of_date
    account_id = seed(db_session)
    snapshot = get_snapshot(db_session, account_id)
    period = quarter_containing(as_of)
    so_far = vat_so_far(period, as_of, snapshot.invoices, snapshot.expenses)
    forecast = forecast_vat(period, as_of, snapshot.invoices, snapshot.expenses)
    proposed = proposed_reserve_transfer(
        forecast.estimated_vat_due,
        snapshot.account.operating_balance,
        snapshot.account.reserve_balance,
    )

    assert [invoice.vat_amount for invoice in snapshot.invoices] == [
        Decimal("1900.00"),
        Decimal("950.00"),
        Decimal("1520.00"),
        Decimal("380.00"),
    ]
    assert so_far.vat_due == Decimal("2565.00")
    assert forecast.estimated_vat_due == Decimal("4085.00")
    assert proposed == Decimal("3585.00")


def test_reset_restores_the_starting_balances(db_session: Session) -> None:
    seed(db_session)
    proposal = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)
    decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)

    reset(db_session)
    account = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account

    assert account.operating_balance == demo_data.OPERATING_BALANCE
    assert account.reserve_balance == demo_data.RESERVE_BALANCE
    assert db_session.scalar(select(func.count()).select_from(Proposal)) == 0
    assert db_session.scalar(select(func.count()).select_from(Transfer)) == 0
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 4


def test_seed_twice_inserts_once(db_session: Session) -> None:
    first = seed(db_session)
    second = seed(db_session)

    assert first == second
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 4
