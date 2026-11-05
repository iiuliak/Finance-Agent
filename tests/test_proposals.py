from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.db.orm import Transfer
from finance_agent.models import ProposalStatus
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.seed import seed
from finance_agent.services.explain import ExplanationFacts, write_explanation
from finance_agent.services.proposals import generate_proposal


def test_template_copies_the_figures_it_is_given() -> None:
    text = write_explanation(
        ExplanationFacts(
            collected_vat=Decimal("2850.00"),
            input_vat=Decimal("285.00"),
            additional_vat=Decimal("1520.00"),
            reserve_balance=Decimal("500.00"),
            estimated_vat_due=Decimal("4085.00"),
            proposed_amount=Decimal("3585.00"),
        )
    )

    assert "€2,850.00" in text
    assert "€285.00" in text
    assert "€1,520.00" in text
    assert "€500.00" in text
    assert "€4,085.00" in text
    assert "€3,585.00" in text


def test_zero_proposal_says_there_is_nothing_to_move() -> None:
    text = write_explanation(
        ExplanationFacts(
            collected_vat=Decimal("2850.00"),
            input_vat=Decimal("285.00"),
            additional_vat=Decimal("1520.00"),
            reserve_balance=Decimal("4085.00"),
            estimated_vat_due=Decimal("4085.00"),
            proposed_amount=Decimal("0.00"),
        )
    )

    assert "nothing to move" in text
    assert "Move €0.00" not in text


def test_generate_proposal_does_not_move_money(db_session: Session) -> None:
    seed(db_session)
    before = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID)

    proposal = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)
    after = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID)
    transfers = db_session.scalar(select(func.count()).select_from(Transfer))

    assert proposal.status == ProposalStatus.PENDING
    assert proposal.vat_due == Decimal("2565.00")
    assert proposal.forecast_vat == Decimal("4085.00")
    assert proposal.proposed_amount == Decimal("3585.00")
    assert "€3,585.00" in proposal.explanation
    assert transfers == 0
    assert after.account.operating_balance == before.account.operating_balance
    assert after.account.reserve_balance == before.account.reserve_balance
