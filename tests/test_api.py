from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from finance_agent.api.main import app, get_session
from finance_agent.demo_data import DEMO_ACCOUNT_ID, OPERATING_BALANCE, RESERVE_BALANCE
from finance_agent.repositories.ledger import get_snapshot
from finance_agent.seed import seed


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_page_offers_the_chat_and_the_decision_buttons(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "/api/chat" in response.text
    assert 'data-decision="approve"' in response.text
    assert 'data-decision="reject"' in response.text


def test_chat_creates_a_pending_proposal_and_approve_moves_money_once(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)

    chat = client.post("/api/chat", json={"message": "How much should I move to my VAT reserve?"})
    proposal = chat.json()["proposal"]

    assert chat.status_code == 200
    assert Decimal(proposal["proposed_amount"]) == Decimal("3585.00")
    assert Decimal(proposal["vat_due"]) == Decimal("2565.00")
    assert Decimal(proposal["forecast_vat"]) == Decimal("4085.00")
    assert proposal["status"] == "pending"
    before = get_snapshot(db_session, DEMO_ACCOUNT_ID).account
    assert before.operating_balance == OPERATING_BALANCE
    assert before.reserve_balance == RESERVE_BALANCE

    approved = client.post(
        f"/api/proposals/{proposal['id']}/decision",
        json={"decision": "approve"},
    )
    account = get_snapshot(db_session, DEMO_ACCOUNT_ID).account

    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert account.operating_balance == Decimal("8415.00")
    assert account.reserve_balance == Decimal("4085.00")

    repeated = client.post(
        f"/api/proposals/{proposal['id']}/decision",
        json={"decision": "approve"},
    )
    again = get_snapshot(db_session, DEMO_ACCOUNT_ID).account

    assert repeated.status_code == 409
    assert again.operating_balance == Decimal("8415.00")
    assert again.reserve_balance == Decimal("4085.00")


def test_reject_leaves_the_balances_unchanged(client: TestClient, db_session: Session) -> None:
    seed(db_session)
    proposal_id = client.post("/api/chat", json={"message": "Set VAT aside."}).json()["proposal"]["id"]

    rejected = client.post(
        f"/api/proposals/{proposal_id}/decision",
        json={"decision": "reject"},
    )
    account = get_snapshot(db_session, DEMO_ACCOUNT_ID).account

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["transfer_id"] is None
    assert account.operating_balance == OPERATING_BALANCE
    assert account.reserve_balance == RESERVE_BALANCE


def test_unknown_proposal_is_not_found(client: TestClient) -> None:
    response = client.post(
        f"/api/proposals/{uuid4()}/decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 404
