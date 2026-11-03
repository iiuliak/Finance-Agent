from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent.db.orm import Invoice, User
from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.seed import seed
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


def test_seed_twice_inserts_once(db_session: Session) -> None:
    first = seed(db_session)
    second = seed(db_session)

    assert first == second
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 4
