from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.db.orm import Account, Transfer
from finance_agent.models import Decision, ProposalStatus, TransferStatus
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.seed import seed
from finance_agent.services.proposals import generate_proposal
from finance_agent.services.transfers import ProposalConflict, decide


def _pending(session: Session):
    seed(session)
    return generate_proposal(session, demo_data.DEMO_ACCOUNT_ID)


def _transfer_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Transfer))


def test_reject_moves_nothing_and_cannot_be_repeated(db_session: Session) -> None:
    proposal = _pending(db_session)

    result = decide(db_session, proposal.id, Decision.REJECT, demo_data.DEMO_USER_ID)
    account = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account

    assert result.status == ProposalStatus.REJECTED
    assert result.transfer_id is None
    assert _transfer_count(db_session) == 0
    assert account.operating_balance == demo_data.OPERATING_BALANCE
    assert account.reserve_balance == demo_data.RESERVE_BALANCE
    with pytest.raises(ProposalConflict):
        decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    unchanged = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account
    assert unchanged.operating_balance == demo_data.OPERATING_BALANCE
    assert unchanged.reserve_balance == demo_data.RESERVE_BALANCE


def test_approve_moves_the_proposed_amount_once(db_session: Session) -> None:
    proposal = _pending(db_session)

    result = decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    account = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account
    transfer = db_session.scalars(select(Transfer)).one()

    assert result.status == ProposalStatus.EXECUTED
    assert result.transfer_id == transfer.id
    assert transfer.amount == Decimal("3585.00")
    assert transfer.status == TransferStatus.COMPLETED
    assert transfer.idempotency_key == str(proposal.id)
    assert account.operating_balance == Decimal("8415.00")
    assert account.reserve_balance == Decimal("4085.00")

    with pytest.raises(ProposalConflict):
        decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    again = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account
    assert again.operating_balance == Decimal("8415.00")
    assert again.reserve_balance == Decimal("4085.00")
    assert _transfer_count(db_session) == 1


def test_approve_of_zero_inserts_no_transfer(db_session: Session) -> None:
    seed(db_session)
    account = db_session.get(Account, demo_data.DEMO_ACCOUNT_ID)
    account.reserve_balance = Decimal("4085.00")
    db_session.flush()
    proposal = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)

    result = decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    balances = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account

    assert proposal.proposed_amount == Decimal("0.00")
    assert result.status == ProposalStatus.EXECUTED
    assert result.transfer_id is None
    assert _transfer_count(db_session) == 0
    assert balances.operating_balance == demo_data.OPERATING_BALANCE
    assert balances.reserve_balance == Decimal("4085.00")


def test_a_new_proposal_supersedes_the_pending_one(db_session: Session) -> None:
    """Approving two cards computed from the same balances must not fill the reserve twice."""
    older = _pending(db_session)
    newer = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)

    with pytest.raises(ProposalConflict) as conflict:
        decide(db_session, older.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    result = decide(db_session, newer.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    account = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account

    assert conflict.value.status == ProposalStatus.SUPERSEDED.value
    assert result.status == ProposalStatus.EXECUTED
    assert _transfer_count(db_session) == 1
    assert account.operating_balance == Decimal("8415.00")
    assert account.reserve_balance == Decimal("4085.00")


def test_proposal_after_an_approval_proposes_zero(db_session: Session) -> None:
    first = _pending(db_session)
    decide(db_session, first.id, Decision.APPROVE, demo_data.DEMO_USER_ID)

    second = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)

    assert second.proposed_amount == Decimal("0.00")


def test_approve_fails_when_the_operating_balance_is_short(db_session: Session) -> None:
    proposal = _pending(db_session)
    account = db_session.get(Account, demo_data.DEMO_ACCOUNT_ID)
    account.operating_balance = Decimal("100.00")
    db_session.flush()

    result = decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    balances = get_snapshot(db_session, demo_data.DEMO_ACCOUNT_ID).account

    assert result.status == ProposalStatus.FAILED
    assert result.transfer_id is None
    assert _transfer_count(db_session) == 0
    assert balances.operating_balance == Decimal("100.00")
    assert balances.reserve_balance == demo_data.RESERVE_BALANCE
