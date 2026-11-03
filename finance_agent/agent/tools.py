import json
from uuid import UUID

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from finance_agent.repositories.ledger import get_account, list_expenses, list_invoices
from finance_agent.services.proposals import generate_proposal

READ_TOOL_NAMES = ("get_invoices", "get_expenses", "get_balance")
PREPARE_TOOL_NAME = "prepare_reserve_proposal"


def build_tools(session: Session, account_id: UUID) -> list[BaseTool]:
    """Tools the model may call. None of them moves money or accepts an amount."""

    @tool
    def get_invoices() -> str:
        """List this account's invoices, including each invoice's VAT and payment dates."""
        invoices = list_invoices(session, account_id)
        return json.dumps([invoice.model_dump(mode="json") for invoice in invoices])

    @tool
    def get_expenses() -> str:
        """List this account's expenses, including the input VAT on each one."""
        expenses = list_expenses(session, account_id)
        return json.dumps([expense.model_dump(mode="json") for expense in expenses])

    @tool
    def get_balance() -> str:
        """Return the operating balance and the reserve balance."""
        account = get_account(session, account_id)
        return json.dumps(
            {
                "operating_balance": str(account.operating_balance),
                "reserve_balance": str(account.reserve_balance),
            }
        )

    @tool
    def prepare_reserve_proposal() -> str:
        """Ask Python to compute a reserve transfer and save it as pending.

        The tool chooses every amount. It does not move money.
        """
        proposal = generate_proposal(session, account_id)
        return proposal.model_dump_json()

    return [get_invoices, get_expenses, get_balance, prepare_reserve_proposal]
