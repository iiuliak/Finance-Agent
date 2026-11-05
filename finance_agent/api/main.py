from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy.orm import Session

from finance_agent.agent.graph import run_turn
from finance_agent.db.session import SessionLocal
from finance_agent.demo_data import DEMO_ACCOUNT_ID, DEMO_USER_ID
from finance_agent.models import (
    ProposalDecisionRequest,
    ProposalDecisionResponse,
    ProposalStatus,
    Schema,
    VATProposalRead,
)
from finance_agent.repositories.ledger import get_account
from finance_agent.services.transfers import ProposalConflict, decide

_PAGE = Path(__file__).resolve().parents[1] / "templates" / "index.html"


class ChatHistoryMessage(Schema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(Schema):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(Schema):
    reply: str
    proposal: VATProposalRead | None = None


class BalanceResponse(Schema):
    operating_balance: Decimal
    reserve_balance: Decimal


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


app = FastAPI(title="VAT Reserve Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_PAGE)


@app.get("/api/balance", response_model=BalanceResponse)
def balance(session: Session = Depends(get_session)) -> BalanceResponse:
    try:
        account = get_account(session, DEMO_ACCOUNT_ID)
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    return BalanceResponse(
        operating_balance=account.operating_balance,
        reserve_balance=account.reserve_balance,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    try:
        turn = run_turn(
            session,
            DEMO_ACCOUNT_ID,
            body.message,
            [(message.role, message.content) for message in body.history],
        )
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail="Demo account not found. Run `python -m finance_agent.seed` first.",
        ) from None
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:
            raise HTTPException(
                status_code=503,
                detail="The language model's free-tier rate limit was hit. Try again in a minute.",
            ) from None
        raise HTTPException(
            status_code=502, detail=f"The language model returned an error: {error}"
        ) from None
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502, detail=f"The language model could not be reached: {error}"
        ) from None
    # Commit before responding, so the card's proposal exists when the user clicks Approve.
    session.commit()
    return ChatResponse(reply=turn.reply, proposal=turn.proposal)


@app.post("/api/proposals/{proposal_id}/decision", response_model=ProposalDecisionResponse)
def decision(
    proposal_id: UUID,
    body: ProposalDecisionRequest,
    session: Session = Depends(get_session),
) -> ProposalDecisionResponse:
    try:
        result = decide(session, proposal_id, body.decision, DEMO_USER_ID)
    except LookupError:
        raise HTTPException(status_code=404, detail="Proposal not found") from None
    except ProposalConflict as conflict:
        detail = (
            "A newer proposal replaced this one. Use the latest card."
            if conflict.status == ProposalStatus.SUPERSEDED.value
            else "This proposal was already decided."
        )
        raise HTTPException(status_code=409, detail=detail) from None
    session.commit()
    return result
