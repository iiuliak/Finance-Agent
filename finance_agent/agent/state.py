from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from finance_agent.models import VATProposalRead


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    account_id: UUID
    proposal: VATProposalRead | None


@dataclass(frozen=True)
class ChatTurn:
    reply: str
    proposal: VATProposalRead | None
