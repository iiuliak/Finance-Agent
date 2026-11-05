import json
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

from finance_agent.agent.state import AgentState, ChatTurn
from finance_agent.agent.template import answer
from finance_agent.agent.tools import TRANSFER_TOOL_NAME, build_tools
from finance_agent.models import VATProposalRead
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
    "Offer to prepare a transfer only when suggested_transfer_to_reserve is above zero. "
    "Call transfer_to_reserve only when the user asks to move, set aside, or reserve money "
    "and a transfer is still needed. "
    "That tool computes the amount and saves a pending proposal; it does not move money. "
    "You cannot approve a transfer. The user does that with the buttons on the card, "
    "so tell them to review the card instead of saying the money has moved. "
    "Mention a card only when transfer_to_reserve returned needs_approval true. "
    "If it returned needs_approval false, say the reserve already covers the estimate "
    "and do not mention a card. "
    "Do not state filing or payment deadlines, or any date that no tool returned. "
    "Answer in a few short sentences of plain text, without markdown or tables."
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
    """
    graph = _template_graph(session) if get_settings().llm_mode == "template" else _openai_graph(session)
    earlier = [
        HumanMessage(content=text) if role == "user" else AIMessage(content=text)
        for role, text in history
    ]
    result = graph.invoke(
        {
            "messages": [*earlier, HumanMessage(content=user_message)],
            "account_id": account_id,
            "proposal": None,
        }
    )
    return ChatTurn(reply=_reply_text(result["messages"]), proposal=result["proposal"])


def _template_graph(session: Session):
    def reply(state: AgentState) -> dict:
        text, proposal = answer(session, state["account_id"], state["messages"][-1].content)
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
        tools = build_tools(session, state["account_id"])
        message = _complete(
            [
                SystemMessage(
                    content=f"{_SYSTEM_PROMPT} Today is {settings.as_of_date.isoformat()}; "
                    "the current quarter has not ended yet."
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
        tools = build_tools(session, state["account_id"])
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


def _complete(
    messages: list[AnyMessage],
    tools: list[BaseTool],
    base_url: str,
    api_key: str,
    model: str,
) -> AIMessage:
    payload = {
        "model": model,
        "messages": [_openai_message(message) for message in messages],
        "tools": [_openai_tool(tool) for tool in tools],
    }
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


def _reply_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content and not message.tool_calls:
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""
