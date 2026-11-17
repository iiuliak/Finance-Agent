import json
from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from finance_agent.agent.tools import build_tools
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


def test_opening_day_and_real_payment_dates_are_on_the_books(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)

    response = client.get("/api/books")
    body = response.json()

    assert response.status_code == 200
    assert body["as_of"] == "2026-11-15"
    assert Decimal(body["vat_due"]) == Decimal("2565.00")
    assert Decimal(body["expected_additional_vat"]) == Decimal("1520.00")
    assert Decimal(body["forecast_vat"]) == Decimal("4085.00")
    assert Decimal(body["proposed_amount"]) == Decimal("3585.00")
    fourth_quarter = [
        invoice for invoice in body["invoices"] if invoice["issue_date"] >= "2026-10-01"
    ]
    assert len(body["invoices"]) == 16
    assert len(body["expenses"]) == 8
    assert [invoice["payment_date"] for invoice in fourth_quarter] == [
        "2026-10-05",
        "2026-11-02",
        "2027-01-05",
        "2026-12-10",
    ]


def test_moving_to_5_november_keeps_the_opening_card(client: TestClient, db_session: Session) -> None:
    seed(db_session)

    response = client.put("/api/as-of", json={"as_of": "2026-11-05"})
    body = response.json()

    assert response.status_code == 200
    assert Decimal(body["vat_due"]) == Decimal("2565.00")
    assert Decimal(body["forecast_vat"]) == Decimal("4085.00")
    assert Decimal(body["proposed_amount"]) == Decimal("3585.00")


def test_moving_to_10_december_counts_the_paid_invoice(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    proposal_id = client.post("/api/chat", json={"message": "Set VAT aside."}).json()["proposal"]["id"]

    moved = client.put("/api/as-of", json={"as_of": "2026-12-10"})
    body = moved.json()
    stale = client.post(f"/api/proposals/{proposal_id}/decision", json={"decision": "approve"})
    account = get_snapshot(db_session, DEMO_ACCOUNT_ID).account

    assert moved.status_code == 200
    assert Decimal(body["vat_due"]) == Decimal("2945.00")
    assert Decimal(body["expected_additional_vat"]) == Decimal("0.00")
    assert Decimal(body["forecast_vat"]) == Decimal("2945.00")
    assert Decimal(body["proposed_amount"]) == Decimal("2445.00")
    assert stale.status_code == 409
    assert account.operating_balance == OPERATING_BALANCE
    assert account.reserve_balance == RESERVE_BALANCE

    fresh = client.post("/api/chat", json={"message": "Set VAT aside."})
    proposal = fresh.json()["proposal"]

    assert Decimal(proposal["vat_due"]) == Decimal("2945.00")
    assert Decimal(proposal["proposed_amount"]) == Decimal("2445.00")
    assert "10 December 2026" in proposal["explanation"]


def test_agent_tools_hide_payments_after_the_chosen_day(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)
    tools = {tool.name: tool for tool in build_tools(db_session, DEMO_ACCOUNT_ID)}

    invoices = json.loads(tools["get_invoices"].invoke({}))["invoices"]
    paid = {invoice["net_amount"]: invoice["payment_date"] for invoice in invoices}

    assert paid["10000.00"] == "2026-10-05"
    assert paid["8000.00"] is None
    assert paid["2000.00"] is None

    client.post(
        "/api/expenses",
        json={"expense_date": "2026-12-01", "gross_amount": "1190.00", "input_vat_amount": "190.00"},
    )
    visible = json.loads(tools["get_expenses"].invoke({}))["expenses"]
    stored = client.get("/api/books").json()

    assert "2026-12-01" not in [expense["expense_date"] for expense in visible]
    assert "2026-12-01" in [expense["expense_date"] for expense in stored["expenses"]]
    assert Decimal(stored["vat_due"]) == Decimal("2565.00")


def test_adding_and_deleting_an_invoice_changes_the_forecast(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session)

    added = client.post(
        "/api/invoices",
        json={
            "net_amount": "1000.00",
            "vat_rate": "0.19",
            "issue_date": "2026-11-01",
            "expected_payment_date": "2026-11-20",
        },
    )
    body = added.json()
    created = next(
        invoice
        for invoice in body["invoices"]
        if invoice["expected_payment_date"] == "2026-11-20"
    )

    assert added.status_code == 200
    assert Decimal(created["vat_amount"]) == Decimal("190.00")
    assert Decimal(body["vat_due"]) == Decimal("2565.00")
    assert Decimal(body["expected_additional_vat"]) == Decimal("1710.00")
    assert Decimal(body["forecast_vat"]) == Decimal("4275.00")
    assert Decimal(body["proposed_amount"]) == Decimal("3775.00")

    removed = client.delete(f"/api/invoices/{created['id']}")

    assert removed.status_code == 200
    assert Decimal(removed.json()["forecast_vat"]) == Decimal("4085.00")
    assert Decimal(removed.json()["proposed_amount"]) == Decimal("3585.00")


def test_balance_change_and_invalid_rows(client: TestClient, db_session: Session) -> None:
    seed(db_session)

    covered = client.put(
        "/api/balances",
        json={"operating_balance": "12000.00", "reserve_balance": "4085.00"},
    )
    assert covered.status_code == 200
    assert Decimal(covered.json()["proposed_amount"]) == Decimal("0.00")

    assert client.put(
        "/api/balances",
        json={"operating_balance": "-1.00", "reserve_balance": "0.00"},
    ).status_code == 422
    assert client.post(
        "/api/invoices",
        json={"net_amount": "1000.00", "vat_rate": "2", "issue_date": "2026-11-01"},
    ).status_code == 422
    assert client.post(
        "/api/expenses",
        json={"expense_date": "2026-11-01", "gross_amount": "100.00", "input_vat_amount": "190.00"},
    ).status_code == 422
    assert client.delete(f"/api/invoices/{uuid4()}").status_code == 404
    assert client.delete(f"/api/expenses/{uuid4()}").status_code == 404

    account = get_snapshot(db_session, DEMO_ACCOUNT_ID).account
    assert account.reserve_balance == Decimal("4085.00")
    assert account.operating_balance == OPERATING_BALANCE
