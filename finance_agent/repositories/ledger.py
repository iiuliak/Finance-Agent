from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from finance_agent.db.orm import Account, Expense, Invoice, Proposal
from finance_agent.models import (
    AccountRead,
    ExpenseRead,
    FinancialSnapshot,
    InvoiceRead,
    ProposalStatus,
    VATProposalDraft,
    VATProposalRead,
)


def get_account(session: Session, account_id: UUID) -> AccountRead:
    row = session.get(Account, account_id)
    if row is None:
        raise LookupError(f"Account {account_id} not found")
    return AccountRead.model_validate(row)


def lock_account(session: Session, account_id: UUID) -> Account:
    """Row-lock the account. Proposal generation and decisions both take this lock first."""
    row = session.scalar(
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise LookupError(f"Account {account_id} not found")
    return row


def supersede_pending_proposals(session: Session, account_id: UUID) -> None:
    """A pending proposal was computed from older balances, so it must not be approved later."""
    session.execute(
        update(Proposal)
        .where(
            Proposal.account_id == account_id,
            Proposal.status == ProposalStatus.PENDING.value,
        )
        .values(status=ProposalStatus.SUPERSEDED.value)
        .execution_options(synchronize_session="fetch")
    )


def list_invoices(session: Session, account_id: UUID) -> list[InvoiceRead]:
    rows = session.scalars(
        select(Invoice)
        .where(Invoice.account_id == account_id)
        .order_by(Invoice.issue_date, Invoice.id)
    ).all()
    return [InvoiceRead.model_validate(row) for row in rows]


def list_expenses(session: Session, account_id: UUID) -> list[ExpenseRead]:
    rows = session.scalars(
        select(Expense)
        .where(Expense.account_id == account_id)
        .order_by(Expense.expense_date, Expense.id)
    ).all()
    return [ExpenseRead.model_validate(row) for row in rows]


def get_snapshot(session: Session, account_id: UUID) -> FinancialSnapshot:
    return FinancialSnapshot(
        account=get_account(session, account_id),
        invoices=list_invoices(session, account_id),
        expenses=list_expenses(session, account_id),
    )


def insert_proposal(session: Session, draft: VATProposalDraft) -> VATProposalRead:
    row = Proposal(
        account_id=draft.account_id,
        period_start=draft.period_start,
        period_end=draft.period_end,
        vat_due=draft.vat_due,
        forecast_vat=draft.forecast_vat,
        proposed_amount=draft.proposed_amount,
        explanation=draft.explanation,
        status=ProposalStatus.PENDING.value,
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return VATProposalRead.model_validate(row)


def get_proposal(session: Session, proposal_id: UUID) -> VATProposalRead:
    row = session.get(Proposal, proposal_id)
    if row is None:
        raise LookupError(f"Proposal {proposal_id} not found")
    return VATProposalRead.model_validate(row)
