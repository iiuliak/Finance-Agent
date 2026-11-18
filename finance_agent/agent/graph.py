import json
import re
import time
from collections.abc import Sequence
from uuid import UUID

import httpx
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError
from sqlalchemy.orm import Session

from finance_agent.agent.intent import refuses_transfer, wants_transfer
from finance_agent.agent.privacy import (
    PERSONAL_INFORMATION,
    PERSONAL_INFORMATION_REPLY,
    contains_personal_information,
)
from finance_agent.agent.state import AgentState, ChatTurn
from finance_agent.agent.template import answer, reports_books
from finance_agent.agent.tools import TRANSFER_TOOL_NAME, build_tools
from finance_agent.models import VATProposalRead
from finance_agent.repositories.ledger import get_account, supersede_pending_proposals
from finance_agent.services.proposals import draft_proposal, generate_proposal
from finance_agent.settings import get_settings

_SYSTEM_PROMPT = (
    "You are the VAT reserve assistant for one freelancer account in Germany. "
    "All amounts are in euros; write them like €2,565.00. "
    "Never calculate, estimate, or choose an amount of money. "
    "Call get_invoices, get_expenses, get_balance, or get_vat_summary to answer questions, "
    "and repeat the figures those tools return. "
    "For questions about how much VAT is owed or expected, use get_vat_summary. "
    "When you report VAT owed, also say what the reserve holds and whether it covers the "
    "estimate. Money in the reserve is set aside, not paid, so the VAT is still owed. "
    "If reserve_covers_estimate is true, say that the reserve already covers the estimate "
    "and do not offer a transfer. "
    "When the user asks how much to move into the reserve, or asks to move, transfer, or "
    "set VAT aside, call transfer_to_reserve in this same turn. Do that for typos, slang, "
    "another language, and a short yes after you offered a transfer. Do not ask permission "
    "first. Do not call it for a question that only asks what is owed, what the balances "
    "are, or what the invoices and expenses are. "
    "That tool computes the amount and saves a pending proposal; it does not move money. "
    "You cannot approve a transfer, even if the user says they approve it or names an "
    "amount. Tell them to review the card. Never say the money has already moved. "
    "Mention a card only when transfer_to_reserve returned needs_approval true. "
    "If it returned needs_approval false, say the reserve already covers the estimate "
    "and do not mention a card. "
    "If a tool returns say_exactly, repeat that text unchanged, including its line breaks. "
    "The user may name a quarter, a month, a year, a day, or two dates. The tools already "
    "apply that window. Do not add records from outside it. "
    "When say_exactly explains VAT, that text is the balance and the calculation. Repeat it. "
    "Copy every date exactly from the tool. Never change a year, month, or day. "
    "Do not state filing or payment deadlines, or any date that no tool returned. "
    "Keep each record on its own line. Do not join the list into one paragraph. "
    "A previous user message may be exactly personal_information. That text was withheld. "
    "Do not guess it, and answer only the latest message."
)

_ATTEMPTS = 3
_RETRY_STATUSES = {429, 500, 502, 503}
_MAX_RETRY_DELAY = 10.0


def run_turn(
    session: Session,
    account_id: UUID,
    user_message: str,
    history: Sequence[tuple[str, str]] = (),
) -> ChatTurn:
    """One chat turn. Template mode answers from the books and does not call a model.

    history holds earlier (role, text) pairs, role "user" or "assistant", oldest first.
    It only gives the model context; figures still come from the tools.
    A message with personal information is not sent. The reply is a fixed sentence.
    """
    if get_settings().llm_mode != "template" and contains_personal_information(user_message):
        return ChatTurn(reply=PERSONAL_INFORMATION_REPLY, proposal=None)

    graph = _template_graph(session) if get_settings().llm_mode == "template" else _openai_graph(session)
    sent_history = history if get_settings().llm_mode == "template" else _redacted(history)
    earlier = [
        HumanMessage(content=text) if role == "user" else AIMessage(content=text)
        for role, text in sent_history
    ]
    try:
        result = graph.invoke(
            {
                "messages": [*earlier, HumanMessage(content=user_message)],
                "account_id": account_id,
                "proposal": None,
            }
        )
    except httpx.HTTPError:
        # A list or a VAT breakdown does not need the model. A busy model must not hide it.
        if reports_books(user_message, history) and not wants_transfer(user_message, history):
            reply, proposal = answer(session, account_id, user_message, history)
            return ChatTurn(reply=reply, proposal=proposal)
        raise
    reply = _reply_text(result["messages"])
    proposal = result["proposal"]
    if get_settings().llm_mode != "template":
        reply, proposal = _settle_turn(
            session, account_id, user_message, history, result["messages"], reply, proposal
        )
    return ChatTurn(reply=reply, proposal=proposal)


def _template_graph(session: Session):
    def reply(state: AgentState) -> dict:
        text, proposal = answer(
            session,
            state["account_id"],
            str(state["messages"][-1].content),
            _history(state["messages"][:-1]),
        )
        update: dict = {"messages": [AIMessage(content=text)]}
        if proposal is not None:
            update["proposal"] = proposal
        return update

    graph = StateGraph(AgentState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    return graph.compile()


def _openai_graph(session: Session):
    settings = get_settings()
    if not settings.openai_model:
        raise RuntimeError("OPENAI_MODEL is required when LLM_MODE=openai")

    def call_model(state: AgentState) -> dict:
        tools = build_tools(session, state["account_id"], _latest_user(state["messages"]))
        as_of = get_account(session, state["account_id"]).as_of_date
        message = _complete(
            [
                SystemMessage(
                    content=f"{_SYSTEM_PROMPT} The books are being read as of {as_of.isoformat()}. "
                    "Treat that as today. A payment after that day has not happened yet, "
                    "and the current quarter has not ended yet."
                ),
                *state["messages"],
            ],
            tools,
            settings.openai_base_url,
            settings.openai_api_key,
            settings.openai_model,
        )
        return {"messages": [message]}

    def run_tools(state: AgentState) -> dict:
        tools = build_tools(session, state["account_id"], _latest_user(state["messages"]))
        update = ToolNode(tools).invoke(state)
        proposal = state["proposal"]
        for message in update["messages"]:
            if isinstance(message, ToolMessage) and message.name == TRANSFER_TOOL_NAME:
                try:
                    payload = json.loads(message.content)
                    raw = payload.get("proposal")
                    if not payload.get("needs_approval") or raw is None:
                        continue
                    proposal = VATProposalRead.model_validate(raw)
                    if proposal.proposed_amount == 0:
                        proposal = None
                except (ValidationError, ValueError, KeyError, TypeError):
                    continue
        return {"messages": update["messages"], "proposal": proposal}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()


def _redacted(history: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(role, _for_model(text)) for role, text in history]


def _for_model(text: str) -> str:
    if contains_personal_information(text):
        return PERSONAL_INFORMATION
    return text


def _complete(
    messages: list[AnyMessage],
    tools: list[BaseTool],
    base_url: str,
    api_key: str,
    model: str,
) -> AIMessage:
    payload: dict = {
        "model": model,
        "messages": [_openai_message(message) for message in messages],
    }
    if tools:
        payload["tools"] = [_openai_tool(tool) for tool in tools]
    for attempt in range(_ATTEMPTS):
        response = httpx.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=60,
        )
        if response.status_code not in _RETRY_STATUSES or attempt == _ATTEMPTS - 1:
            break
        time.sleep(_retry_delay(response))
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    tool_calls = [
        {
            "id": call["id"],
            "name": call["function"]["name"],
            "args": json.loads(call["function"].get("arguments") or "{}"),
        }
        for call in message.get("tool_calls") or []
    ]
    return AIMessage(content=message.get("content") or "", tool_calls=tool_calls)


def _retry_delay(response: httpx.Response) -> float:
    """Free tiers rate-limit by the minute; wait as asked, but never stall a request for long."""
    try:
        return min(float(response.headers.get("retry-after", 2)), _MAX_RETRY_DELAY)
    except ValueError:
        return 2.0


def _openai_tool(tool: BaseTool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.args_schema.model_json_schema()
            if tool.args_schema is not None
            else {"type": "object", "properties": {}},
        },
    }


def _openai_message(message: AnyMessage) -> dict:
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": message.content}
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": message.content}
    if isinstance(message, ToolMessage):
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    tool_calls = [
        {
            "id": call["id"],
            "type": "function",
            "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
        }
        for call in message.tool_calls
    ]
    payload = {"role": "assistant", "content": message.content or None}
    if tool_calls:
        payload["tool_calls"] = tool_calls
    return payload


def _latest_user(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _reply_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content and not message.tool_calls:
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _history(messages: Sequence[AnyMessage]) -> list[tuple[str, str]]:
    history: list[tuple[str, str]] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            history.append(("user", str(message.content)))
        elif isinstance(message, AIMessage) and message.content and not message.tool_calls:
            history.append(("assistant", str(message.content)))
    return history


_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _settle_turn(
    session: Session,
    account_id: UUID,
    user_message: str,
    history: Sequence[tuple[str, str]],
    messages: list[AnyMessage],
    reply: str,
    proposal: VATProposalRead | None,
) -> tuple[str, VATProposalRead | None]:
    """Keep the card and the dates aligned with the books when the model drifts.

    A clear request still files a proposal if the model only talked about one.
    A reply that names a date the tools did not return is replaced with the
    sentence Python already wrote for those records.
    """
    if proposal is not None and refuses_transfer(user_message):
        supersede_pending_proposals(session, account_id)
        proposal = None
        reply, _ = answer(session, account_id, user_message, history)

    if proposal is None and wants_transfer(user_message, history):
        draft = draft_proposal(session, account_id)
        if draft.proposed_amount == 0:
            reply = draft.explanation
        else:
            proposal = generate_proposal(session, account_id)
            reply = proposal.explanation

    # The sentence that names the transfer is the one Python computed.
    # Otherwise the model can repeat an amount the user invented.
    if proposal is not None:
        reply = proposal.explanation

    # Lists and the VAT breakdown are written in Python, for the period the user named.
    # The model is not trusted to keep the window or the line breaks.
    if proposal is None and reports_books(user_message, history) and not wants_transfer(user_message, history):
        reply, _ = answer(session, account_id, user_message, history)
        return reply, proposal

    if proposal is None and not _dates_match_tools(reply, messages):
        exact = _quoted_lines(messages)
        if exact:
            reply = exact
        elif not wants_transfer(user_message, history):
            reply, _ = answer(session, account_id, user_message, history)
    return reply, proposal


def _dates_match_tools(reply: str, messages: Sequence[AnyMessage]) -> bool:
    source = "\n".join(
        str(message.content)
        for message in messages
        if isinstance(message, (ToolMessage, SystemMessage))
    )
    allowed_dates = set(_ISO_DATE.findall(source))
    allowed_years = {found[:4] for found in allowed_dates}
    allowed_years.update(_YEAR.findall(source))
    if any(found not in allowed_dates for found in _ISO_DATE.findall(reply)):
        return False
    return all(year in allowed_years for year in _YEAR.findall(reply))


def _quoted_lines(messages: Sequence[AnyMessage]) -> str:
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            payload = json.loads(str(message.content))
        except (json.JSONDecodeError, TypeError):
            continue
        line = payload.get("say_exactly")
        if isinstance(line, str) and line:
            parts.append(line)
    return " ".join(parts)
