import json
from datetime import timedelta
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from finance_agent.agent.template import (
    _chosen_expenses,
    _chosen_invoices,
    expense_lines,
    explain_vat,
    invoice_lines,
)
from finance_agent.agent.when import view_for
from finance_agent.domain.forecast import forecast_vat, known_as_of, vat_so_far
from finance_agent.domain.proposal import proposed_reserve_transfer
from finance_agent.repositories.ledger import get_account, get_snapshot
from finance_agent.services.proposals import draft_proposal, generate_proposal

READ_TOOL_NAMES = ("get_invoices", "get_expenses", "get_balance", "get_vat_summary")
TRANSFER_TOOL_NAME = "transfer_to_reserve"
APPROVAL_REQUIRED_TOOL_NAMES = frozenset({TRANSFER_TOOL_NAME})
CURRENCY = "EUR"


def build_tools(session: Session, account_id: UUID, message: str = "") -> list[BaseTool]:
    """Tools the model may call. None of them moves money or accepts an amount.

    A month, quarter, year, or day in message is applied here. The model does not
    choose the window, so it cannot move the dates.
    """

    @tool
    def get_invoices() -> str:
        """List this account's invoices, including each invoice's VAT.

        The list is the period the user named, or every invoice known on the
        chosen day when they named none. A payment dated after that day is omitted,
        so the invoice looks unpaid. Repeat say_exactly unchanged, including its line breaks.
        """
        snapshot = get_snapshot(session, account_id)
        today = snapshot.account.as_of_date
        view = view_for(message, today, "invoice")
        invoices, _expenses = known_as_of(view.list_as_of, snapshot.invoices, snapshot.expenses)
        chosen = _chosen_invoices(invoices, view, message)
        return json.dumps(
            {
                "currency": CURRENCY,
                "say_exactly": invoice_lines(chosen, view.label),
                "invoices": [invoice.model_dump(mode="json") for invoice in chosen],
            }
        )

    @tool
    def get_expenses() -> str:
        """List this account's expenses, including each one's input VAT.

        The list is the period the user named, or every expense known on the
        chosen day when they named none. An expense dated after that day is omitted.
        Repeat say_exactly unchanged, including its line breaks.
        """
        snapshot = get_snapshot(session, account_id)
        today = snapshot.account.as_of_date
        view = view_for(message, today, "expense")
        _invoices, expenses = known_as_of(view.list_as_of, snapshot.invoices, snapshot.expenses)
        chosen = _chosen_expenses(expenses, view)
        return json.dumps(
            {
                "currency": CURRENCY,
                "say_exactly": expense_lines(chosen, view.label),
                "expenses": [expense.model_dump(mode="json") for expense in chosen],
            }
        )

    @tool
    def get_balance() -> str:
        """Return the operating balance and the reserve balance."""
        account = get_account(session, account_id)
        return json.dumps(
            {
                "currency": CURRENCY,
                "operating_balance": str(account.operating_balance),
                "reserve_balance": str(account.reserve_balance),
            }
        )

    @tool
    def get_vat_summary() -> str:
        """Return this quarter's VAT figures, already calculated: VAT collected, input VAT,
        VAT already due, VAT still expected from open invoices, the quarter-end estimate,
        the reserve balance, whether the reserve covers the estimate, and the transfer that
        would fill the gap.
        """
        snapshot = get_snapshot(session, account_id)
        today = snapshot.account.as_of_date
        view = view_for(message, today, "vat")
        as_of = view.vat_as_of
        period = view.period
        so_far = vat_so_far(period, as_of, snapshot.invoices, snapshot.expenses)
        forecast = forecast_vat(period, as_of, snapshot.invoices, snapshot.expenses)
        account = snapshot.account
        suggested = proposed_reserve_transfer(
            forecast.estimated_vat_due, account.operating_balance, account.reserve_balance
        )
        return json.dumps(
            {
                "currency": CURRENCY,
                "as_of": as_of.isoformat(),
                "quarter_start": period.period_start.isoformat(),
                "quarter_last_day": (period.period_end - timedelta(days=1)).isoformat(),
                "vat_collected": str(so_far.collected_vat),
                "input_vat": str(so_far.input_vat),
                "vat_already_due": str(so_far.vat_due),
                "vat_expected_from_open_invoices": str(forecast.expected_additional_vat),
                "estimated_vat_at_quarter_end": str(forecast.estimated_vat_due),
                "reserve_balance": str(account.reserve_balance),
                "reserve_covers_estimate": account.reserve_balance >= forecast.estimated_vat_due,
                "suggested_transfer_to_reserve": str(suggested),
                "say_exactly": explain_vat(
                    view,
                    today,
                    snapshot.invoices,
                    snapshot.expenses,
                    account.reserve_balance,
                    account.operating_balance,
                ),
            }
        )

    @tool(TRANSFER_TOOL_NAME)
    def transfer_to_reserve() -> str:
        """Request a transfer of the VAT amount into the tax reserve. Needs the user's approval.

        Call this only when the user asks to move, set aside, or reserve money.
        Python computes the amount and saves it as a pending proposal. No money moves
        until the user clicks Approve on the card.
        """
        draft = draft_proposal(session, account_id)
        if draft.proposed_amount == 0:
            account = get_account(session, account_id)
            return json.dumps(
                {
                    "currency": CURRENCY,
                    "needs_approval": False,
                    "note": (
                        "The reserve already covers the estimate. Do not show a card "
                        "and do not ask the user to approve anything."
                    ),
                    "proposal": None,
                    "vat_already_due": str(draft.vat_due),
                    "estimated_vat_at_quarter_end": str(draft.forecast_vat),
                    "reserve_balance": str(account.reserve_balance),
                    "suggested_transfer_to_reserve": "0.00",
                }
            )
        proposal = generate_proposal(session, account_id)
        return json.dumps(
            {
                "currency": CURRENCY,
                "needs_approval": True,
                "note": "Pending until the user clicks Approve on the card.",
                "proposal": proposal.model_dump(mode="json"),
            }
        )

    return [get_invoices, get_expenses, get_balance, get_vat_summary, transfer_to_reserve]
