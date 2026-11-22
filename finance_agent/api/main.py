from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from finance_agent.agent.graph import run_turn
from finance_agent.db.session import SessionLocal
from finance_agent.demo_data import DEMO_ACCOUNT_ID, DEMO_USER_ID
from finance_agent.models import (
    BooksRead,
    ExpenseCreate,
    InvoiceCreate,
    NonNegativeMoney,
    PositiveMoney,
    ProposalDecisionRequest,
    ProposalDecisionResponse,
    ProposalStatus,
    Schema,
    VATProposalRead,
    VATRate,
)
from finance_agent.repositories.ledger import get_account
from finance_agent.services.books import (
    add_expense,
    add_invoice,
    delete_expense,
    delete_invoice,
    describe_books,
    set_as_of,
    set_balances,
)
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


class AsOfRequest(Schema):
    as_of: date


class BalancesRequest(Schema):
    operating_balance: NonNegativeMoney
    reserve_balance: NonNegativeMoney


class InvoiceWrite(Schema):
    net_amount: PositiveMoney
    vat_rate: VATRate
    issue_date: date
    payment_date: date | None = None
    expected_payment_date: date | None = None


class ExpenseWrite(Schema):
    expense_date: date
    gross_amount: PositiveMoney
    input_vat_amount: NonNegativeMoney

    @model_validator(mode="after")
    def validate_input_vat(self) -> ExpenseWrite:
        if self.input_vat_amount > self.gross_amount:
            raise ValueError("input_vat_amount cannot exceed gross_amount")
        return self


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


def _books(session: Session) -> BooksRead:
    try:
        return describe_books(session, DEMO_ACCOUNT_ID)
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None


@app.get("/api/books", response_model=BooksRead)
def books(session: Session = Depends(get_session)) -> BooksRead:
    return _books(session)


@app.put("/api/as-of", response_model=BooksRead)
def as_of(body: AsOfRequest, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = set_as_of(session, DEMO_ACCOUNT_ID, body.as_of)
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    session.commit()
    return result


@app.put("/api/balances", response_model=BooksRead)
def balances(body: BalancesRequest, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = set_balances(
            session, DEMO_ACCOUNT_ID, body.operating_balance, body.reserve_balance
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    session.commit()
    return result


@app.post("/api/invoices", response_model=BooksRead)
def create_invoice(body: InvoiceWrite, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = add_invoice(
            session,
            DEMO_ACCOUNT_ID,
            InvoiceCreate(account_id=DEMO_ACCOUNT_ID, **body.model_dump()),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    session.commit()
    return result


@app.delete("/api/invoices/{invoice_id}", response_model=BooksRead)
def remove_invoice(invoice_id: UUID, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = delete_invoice(session, DEMO_ACCOUNT_ID, invoice_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Invoice not found") from None
    session.commit()
    return result


@app.post("/api/expenses", response_model=BooksRead)
def create_expense(body: ExpenseWrite, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = add_expense(
            session,
            DEMO_ACCOUNT_ID,
            ExpenseCreate(account_id=DEMO_ACCOUNT_ID, **body.model_dump()),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Demo account not found") from None
    session.commit()
    return result


@app.delete("/api/expenses/{expense_id}", response_model=BooksRead)
def remove_expense(expense_id: UUID, session: Session = Depends(get_session)) -> BooksRead:
    try:
        result = delete_expense(session, DEMO_ACCOUNT_ID, expense_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Expense not found") from None
    session.commit()
    return result


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
                detail="The assistant is busy. Try again in a minute.",
            ) from None
        raise HTTPException(
            status_code=502, detail="I couldn't answer just now. Try again."
        ) from None
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502, detail="I couldn't answer just now. Try again."
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
            "This proposal is out of date. Ask again if you still want to move the money."
            if conflict.status == ProposalStatus.SUPERSEDED.value
            else "This proposal was already decided."
        )
        raise HTTPException(status_code=409, detail=detail) from None
    session.commit()
    return result
