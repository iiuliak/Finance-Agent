import json
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
from finance_agent.agent.tools import PREPARE_TOOL_NAME, build_tools
from finance_agent.models import VATProposalRead
from finance_agent.settings import get_settings

_SYSTEM_PROMPT = (
    "You are the VAT reserve assistant for one freelancer account. "
    "Never calculate, estimate, or choose an amount of money. "
    "Call get_invoices, get_expenses, or get_balance to answer questions, "
    "and repeat the figures those tools return. "
    "When the user should move VAT into the reserve, call prepare_reserve_proposal. "
    "That tool computes the amount and saves a pending proposal. "
    "You cannot approve a transfer or move money. The user does that with the buttons on the card."
)


def run_turn(session: Session, account_id: UUID, user_message: str) -> ChatTurn:
    """One chat turn. Template mode answers from the books and does not call a model."""
    graph = _template_graph(session) if get_settings().llm_mode == "template" else _openai_graph(session)
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=user_message)],
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
    if not settings.openai_base_url or not settings.openai_model:
        raise RuntimeError("OPENAI_BASE_URL and OPENAI_MODEL are required when LLM_MODE=openai")

    def call_model(state: AgentState) -> dict:
        tools = build_tools(session, state["account_id"])
        message = _complete(
            [SystemMessage(content=_SYSTEM_PROMPT), *state["messages"]],
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
            if isinstance(message, ToolMessage) and message.name == PREPARE_TOOL_NAME:
                try:
                    proposal = VATProposalRead.model_validate_json(message.content)
                except ValidationError:
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
    response = httpx.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [_openai_message(message) for message in messages],
            "tools": [_openai_tool(tool) for tool in tools],
        },
        timeout=60,
    )
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
