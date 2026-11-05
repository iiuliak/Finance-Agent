import json
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from finance_agent import demo_data
from finance_agent.agent import graph
from finance_agent.agent.graph import run_turn
from finance_agent.agent.tools import (
    APPROVAL_REQUIRED_TOOL_NAMES,
    READ_TOOL_NAMES,
    TRANSFER_TOOL_NAME,
    build_tools,
)
from finance_agent.db.orm import Account, Proposal, Transfer
from finance_agent.models import Decision, ProposalStatus, VATProposalRead
from finance_agent.seed import seed
from finance_agent.services.proposals import generate_proposal
from finance_agent.services.transfers import decide


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


def test_model_turn_calls_the_transfer_tool_and_moves_nothing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scripted model asks for the transfer; the turn still ends with a pending proposal."""
    seed(db_session)
    monkeypatch.setenv("LLM_MODE", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "scripted")
    replies = iter(
        [
            AIMessage(content="", tool_calls=[{"id": "call-1", "name": TRANSFER_TOOL_NAME, "args": {}}]),
            AIMessage(content="Review the card and approve it if it looks right."),
        ]
    )
    seen: list[list] = []

    def fake_complete(messages, *args):
        seen.append(messages)
        return next(replies)

    monkeypatch.setattr(graph, "_complete", fake_complete)

    turn = run_turn(
        db_session,
        demo_data.DEMO_ACCOUNT_ID,
        "Yes, I'd like that.",
        [("user", "How much VAT do I owe?"), ("assistant", "€2,565.00. Shall I set it aside?")],
    )

    assert [message.content for message in seen[0][1:]] == [
        "How much VAT do I owe?",
        "€2,565.00. Shall I set it aside?",
        "Yes, I'd like that.",
    ]
    account = db_session.get(Account, demo_data.DEMO_ACCOUNT_ID)

    assert turn.reply == "Review the card and approve it if it looks right."
    assert turn.proposal is not None
    assert turn.proposal.status == ProposalStatus.PENDING
    assert turn.proposal.proposed_amount == Decimal("3585.00")
    assert db_session.scalar(select(func.count()).select_from(Transfer)) == 0
    assert account.reserve_balance == demo_data.RESERVE_BALANCE


def test_model_tools_take_no_arguments() -> None:
    tools = build_tools(session=None, account_id=demo_data.DEMO_ACCOUNT_ID)  # type: ignore[arg-type]
    names = [tool.name for tool in tools]

    assert names == [*READ_TOOL_NAMES, TRANSFER_TOOL_NAME]
    assert APPROVAL_REQUIRED_TOOL_NAMES == {TRANSFER_TOOL_NAME}
    for tool in tools:
        assert tool.args == {}


def test_vat_summary_tool_reports_the_figures_without_a_proposal(db_session: Session) -> None:
    seed(db_session)
    tools = {tool.name: tool for tool in build_tools(db_session, demo_data.DEMO_ACCOUNT_ID)}

    summary = json.loads(tools["get_vat_summary"].invoke({}))

    assert summary["currency"] == "EUR"
    assert summary["vat_collected"] == "2850.00"
    assert summary["input_vat"] == "285.00"
    assert summary["vat_already_due"] == "2565.00"
    assert summary["vat_expected_from_open_invoices"] == "1520.00"
    assert summary["estimated_vat_at_quarter_end"] == "4085.00"
    assert summary["reserve_balance"] == "500.00"
    assert summary["reserve_covers_estimate"] is False
    assert summary["suggested_transfer_to_reserve"] == "3585.00"
    assert db_session.scalar(select(func.count()).select_from(Proposal)) == 0


def test_vat_summary_after_approval_says_the_reserve_covers_it(db_session: Session) -> None:
    seed(db_session)
    proposal = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)
    decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    tools = {tool.name: tool for tool in build_tools(db_session, demo_data.DEMO_ACCOUNT_ID)}

    summary = json.loads(tools["get_vat_summary"].invoke({}))
    template_reply = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "How much VAT do I owe?")

    assert summary["vat_already_due"] == "2565.00"
    assert summary["reserve_balance"] == "4085.00"
    assert summary["reserve_covers_estimate"] is True
    assert summary["suggested_transfer_to_reserve"] == "0.00"
    assert "already covers" in template_reply.reply


def test_transfer_tool_files_nothing_when_the_reserve_covers_the_estimate(db_session: Session) -> None:
    seed(db_session)
    proposal = generate_proposal(db_session, demo_data.DEMO_ACCOUNT_ID)
    decide(db_session, proposal.id, Decision.APPROVE, demo_data.DEMO_USER_ID)
    tools = {tool.name: tool for tool in build_tools(db_session, demo_data.DEMO_ACCOUNT_ID)}

    output = json.loads(tools[TRANSFER_TOOL_NAME].invoke({}))
    turn = run_turn(db_session, demo_data.DEMO_ACCOUNT_ID, "Set VAT aside.")

    assert output["needs_approval"] is False
    assert output["proposal"] is None
    assert turn.proposal is None
    assert "nothing to move" in turn.reply
    assert db_session.scalar(select(func.count()).select_from(Proposal)) == 1


def test_transfer_tool_only_files_a_pending_proposal(db_session: Session) -> None:
    seed(db_session)
    tools = {tool.name: tool for tool in build_tools(db_session, demo_data.DEMO_ACCOUNT_ID)}

    output = json.loads(tools[TRANSFER_TOOL_NAME].invoke({}))
    result = VATProposalRead.model_validate_json(json.dumps(output["proposal"]))
    account = db_session.get(Account, demo_data.DEMO_ACCOUNT_ID)

    assert result.status == ProposalStatus.PENDING
    assert result.proposed_amount == Decimal("3585.00")
    assert db_session.scalar(select(func.count()).select_from(Transfer)) == 0
    assert account.operating_balance == demo_data.OPERATING_BALANCE
    assert account.reserve_balance == demo_data.RESERVE_BALANCE
