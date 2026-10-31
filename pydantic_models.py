from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# -------------------------- Reusable types --------------------------
Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2)]
NonNegativeMoney = Annotated[
    Decimal, Field(ge=0, max_digits=14, decimal_places=2)
]
PositiveMoney = Annotated[
    Decimal, Field(gt=0, max_digits=14, decimal_places=2)
]
VATRate = Annotated[
    Decimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)
]


class Schema(BaseModel):
    # from_attributes lets Read models validate SQLAlchemy ORM objects.
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class TransferStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


# -------------------------- Users / accounts --------------------------
class UserCreate(Schema):
    name: str = Field(min_length=1, max_length=120)


class UserRead(UserCreate):
    id: UUID


class AccountCreate(Schema):
    user_id: UUID
    operating_balance: NonNegativeMoney = Decimal("0.00")
    reserve_balance: NonNegativeMoney = Decimal("0.00")


class AccountRead(AccountCreate):
    id: UUID
    updated_at: datetime


# ----------------------------- Invoices -----------------------------
class InvoiceCreate(Schema):
    account_id: UUID
    net_amount: PositiveMoney
    vat_rate: VATRate  # e.g. Decimal("0.1900") for 19%
    issue_date: date
    payment_date: date | None = None
    expected_payment_date: date | None = None


class InvoiceRead(InvoiceCreate):
    id: UUID
    vat_amount: NonNegativeMoney  # calculated by PostgreSQL generated column


# ----------------------------- Expenses -----------------------------
class ExpenseCreate(Schema):
    account_id: UUID
    expense_date: date
    gross_amount: PositiveMoney
    input_vat_amount: NonNegativeMoney

    @model_validator(mode="after")
    def validate_input_vat(self) -> ExpenseCreate:
        if self.input_vat_amount > self.gross_amount:
            raise ValueError("input_vat_amount cannot exceed gross_amount")
        return self


class ExpenseRead(ExpenseCreate):
    id: UUID


# ------------------------- VAT computations -------------------------
class VATPeriod(Schema):
    period_start: date
    period_end: date  # exclusive, e.g. 2027-01-01 for 2026 Q4

    @model_validator(mode="after")
    def validate_period(self) -> VATPeriod:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be later than period_start")
        return self


class VATCalculation(VATPeriod):
    collected_vat: NonNegativeMoney
    input_vat: NonNegativeMoney
    net_vat: Money  # may be negative (input-VAT credit)
    vat_due: NonNegativeMoney  # max(net_vat, 0)

    @model_validator(mode="after")
    def validate_arithmetic(self) -> VATCalculation:
        if self.net_vat != self.collected_vat - self.input_vat:
            raise ValueError("net_vat must equal collected_vat - input_vat")
        if self.vat_due != max(self.net_vat, Decimal("0.00")):
            raise ValueError("vat_due must equal max(net_vat, 0)")
        return self


class VATForecast(VATPeriod):
    as_of: date
    method: str = "expected_payment_dates"
    expected_additional_vat: NonNegativeMoney
    estimated_vat_due: NonNegativeMoney

    @model_validator(mode="after")
    def validate_as_of(self) -> VATForecast:
        if not self.period_start <= self.as_of < self.period_end:
            raise ValueError("as_of must be within the forecast quarter")
        return self


# ---------------------- Proposal / approval -----------------------
class ProposalGenerateRequest(Schema):
    # The backend selects the quarter and computes the money amounts.
    account_id: UUID


class ProposalExplanation(Schema):
    # Give the LLM ONLY this output shape, not control over money amounts.
    explanation: str = Field(min_length=1, max_length=2000)


class VATProposalDraft(VATPeriod):
    # Internal service output. Do not accept this from a public API client.
    account_id: UUID
    vat_due: NonNegativeMoney
    forecast_vat: NonNegativeMoney
    proposed_amount: NonNegativeMoney
    explanation: str = Field(min_length=1, max_length=2000)


class VATProposalRead(VATProposalDraft):
    id: UUID
    status: ProposalStatus
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime


class ProposalDecisionRequest(Schema):
    # Proposal ID comes from the URL; approver identity from authentication.
    decision: Decision


class ProposalDecisionResponse(Schema):
    proposal_id: UUID
    status: ProposalStatus
    transfer_id: UUID | None = None


# ----------------------------- Transfers -----------------------------
class TransferCommand(Schema):
    # Internal-only. Never expose as an unrestricted public endpoint.
    proposal_id: UUID
    amount: PositiveMoney
    idempotency_key: str = Field(min_length=1, max_length=255)


class TransferRead(TransferCommand):
    id: UUID
    status: TransferStatus
    created_at: datetime
    executed_at: datetime | None = None


# --------------------------- Agent inputs ---------------------------
class FinancialSnapshot(Schema):
    """Optional validated value passed between LangGraph nodes."""
    account: AccountRead
    invoices: list[InvoiceRead]
    expenses: list[ExpenseRead]

