from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.agent.graph import run_turn
from finance_agent.agent.tools import PREPARE_TOOL_NAME, READ_TOOL_NAMES, build_tools
from finance_agent.db.orm import Proposal, Transfer
from finance_agent.models import ProposalStatus
from finance_agent.seed import seed


def test_template_turn_answers_without_preparing_a_proposal(db_session: Session) -> None:
    seed(db_session)

    balance = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "What is in my reserve?")
    vat = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "How much VAT do I owe?")
    invoices = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "Which invoices are unpaid?")

    assert balance.proposal is None
    assert "€12,000.00" in balance.reply
    assert "€500.00" in balance.reply
    assert vat.proposal is None
    assert "€2,565.00" in vat.reply
    assert invoices.proposal is None
    assert "unpaid" in invoices.reply
    assert "€8,000.00" in invoices.reply
    assert db_session.scalar(select(func.count()).select_from(Proposal)) == 0
    assert db_session.scalar(select(func.count()).select_from(Transfer)) == 0


def test_template_turn_prepares_a_proposal_and_moves_nothing(db_session: Session) -> None:
    seed(db_session)

    turn = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "How much should I move to my VAT reserve?")

    assert turn.proposal is not None
    assert turn.proposal.status == ProposalStatus.PENDING
    assert turn.proposal.vat_due == Decimal("2565.00")
    assert turn.proposal.forecast_vat == Decimal("4085.00")
    assert turn.proposal.proposed_amount == Decimal("3585.00")
    assert "€3,585.00" in turn.reply
    assert db_session.scalar(select(func.count()).select_from(Proposal)) == 1
    assert db_session.scalar(select(func.count()).select_from(Transfer)) == 0


def test_model_tools_cannot_choose_an_amount_or_move_money() -> None:
    tools = build_tools(session=None, account_id=demo_data.DEMO_ACCOUNT_ID)  # type: ignore[arg-type]
    names = [tool.name for tool in tools]

    assert tuple(names[:3]) == READ_TOOL_NAMES
    assert names[3] == PREPARE_TOOL_NAME
    assert "decide" not in names
    assert "transfer" not in names
    for tool in tools:
        assert "amount" not in tool.args
        assert "balance" not in tool.args
