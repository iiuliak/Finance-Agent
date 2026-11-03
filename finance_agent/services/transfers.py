from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_agent.db.orm import Account, Proposal, Transfer
from finance_agent.domain.money import money
from finance_agent.models import (
    Decision,
    ProposalDecisionResponse,
    ProposalStatus,
    TransferStatus,
)


class ProposalConflict(Exception):
    """The proposal was already decided, so this call changes nothing."""

    def __init__(self, proposal_id: UUID, status: str) -> None:
        self.proposal_id = proposal_id
        self.status = status
        super().__init__(f"Proposal {proposal_id} is already {status}")


def decide(
    session: Session,
    proposal_id: UUID,
    decision: Decision,
    approver_id: UUID,
) -> ProposalDecisionResponse:
    """Approve or reject a pending proposal. Money moves only on a positive approval."""
    proposal = session.scalar(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise LookupError(f"Proposal {proposal_id} not found")
    if proposal.status != ProposalStatus.PENDING.value:
        raise ProposalConflict(proposal.id, proposal.status)

    proposal.approved_by = approver_id
    proposal.approved_at = datetime.now(UTC)
    transfer_id = None

    if decision is Decision.REJECT:
        proposal.status = ProposalStatus.REJECTED.value
    elif proposal.proposed_amount == 0:
        proposal.status = ProposalStatus.EXECUTED.value
    else:
        transfer_id = _move_to_reserve(session, proposal)

    session.flush()
    return ProposalDecisionResponse(
        proposal_id=proposal.id,
        status=ProposalStatus(proposal.status),
        transfer_id=transfer_id,
    )


def _move_to_reserve(session: Session, proposal: Proposal) -> UUID | None:
    account = session.scalar(
        select(Account).where(Account.id == proposal.account_id).with_for_update()
    )
    if account is None:
        raise LookupError(f"Account {proposal.account_id} not found")
    if account.operating_balance < proposal.proposed_amount:
        proposal.status = ProposalStatus.FAILED.value
        return None

    account.operating_balance = money(account.operating_balance - proposal.proposed_amount)
    account.reserve_balance = money(account.reserve_balance + proposal.proposed_amount)
    transfer = Transfer(
        proposal_id=proposal.id,
        amount=proposal.proposed_amount,
        idempotency_key=str(proposal.id),
        status=TransferStatus.COMPLETED.value,
        executed_at=proposal.approved_at,
    )
    session.add(transfer)
    session.flush()
    proposal.status = ProposalStatus.EXECUTED.value
    return transfer.id
