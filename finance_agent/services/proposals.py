from uuid import UUID

from sqlalchemy.orm import Session

from finance_agent.domain.forecast import forecast_vat, vat_so_far
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.models import VATProposalDraft, VATProposalRead
from finance_agent.repositories.ledger import (
    get_snapshot,
    insert_proposal,
    lock_account,
    supersede_pending_proposals,
)
from finance_agent.services.explain import ExplanationFacts, write_explanation
from finance_agent.settings import get_settings


def draft_proposal(session: Session, account_id: UUID) -> VATProposalDraft:
    """Compute the figures for a proposal. Does not write a row and does not move money."""
    as_of = get_settings().as_of_date
    lock_account(session, account_id)
    snapshot = get_snapshot(session, account_id)
    period = quarter_containing(as_of)
    so_far = vat_so_far(period, as_of, snapshot.invoices, snapshot.expenses)
    forecast = forecast_vat(period, as_of, snapshot.invoices, snapshot.expenses)
    proposed_amount = proposed_reserve_transfer(
        forecast.estimated_vat_due,
        snapshot.account.operating_balance,
        snapshot.account.reserve_balance,
    )
    explanation = write_explanation(
        ExplanationFacts(
            collected_vat=so_far.collected_vat,
            input_vat=so_far.input_vat,
            additional_vat=forecast.expected_additional_vat,
            reserve_balance=snapshot.account.reserve_balance,
            estimated_vat_due=forecast.estimated_vat_due,
            proposed_amount=proposed_amount,
        )
    )
    return VATProposalDraft(
        account_id=account_id,
        period_start=period.period_start,
        period_end=period.period_end,
        vat_due=so_far.vat_due,
        forecast_vat=forecast.estimated_vat_due,
        proposed_amount=proposed_amount,
        explanation=explanation,
    )


def generate_proposal(session: Session, account_id: UUID) -> VATProposalRead:
    """Compute a pending reserve proposal. Does not move money and does not commit.

    Older pending proposals for the account are superseded, so at most one can be approved.
    """
    draft = draft_proposal(session, account_id)
    supersede_pending_proposals(session, account_id)
    return insert_proposal(session, draft)
