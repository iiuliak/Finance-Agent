from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

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
    Schema,
    VATProposalRead,
)
from finance_agent.services.transfers import ProposalConflict, decide

_PAGE = Path(__file__).resolve().parents[1] / "templates" / "index.html"


class ChatRequest(Schema):
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(Schema):
    reply: str
    proposal: VATProposalRead | None = None


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


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, session: Session = Depends(get_session)) -> ChatResponse:
    try:
        turn = run_turn(session, DEMO_ACCOUNT_ID, body.message)
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    return ChatResponse(reply=turn.reply, proposal=turn.proposal)


@app.post("/api/proposals/{proposal_id}/decision", response_model=ProposalDecisionResponse)
def decision(
    proposal_id: UUID,
    body: ProposalDecisionRequest,
    session: Session = Depends(get_session),
) -> ProposalDecisionResponse:
    try:
        return decide(session, proposal_id, body.decision, DEMO_USER_ID)
    except LookupError:
        raise HTTPException(status_code=404, detail="Proposal not found") from None
    except ProposalConflict:
        raise HTTPException(status_code=409, detail="Proposal was already decided") from None
