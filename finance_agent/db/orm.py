import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

MONEY = Numeric(14, 2)
VAT_RATE = Numeric(5, 4)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("char_length(name) >= 1", name="name_not_empty"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("operating_balance >= 0", name="operating_balance_non_negative"),
        CheckConstraint("reserve_balance >= 0", name="reserve_balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operating_balance: Mapped[Decimal] = mapped_column(MONEY, server_default="0.00")
    reserve_balance: Mapped[Decimal] = mapped_column(MONEY, server_default="0.00")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("net_amount > 0", name="net_amount_positive"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 1", name="vat_rate_fraction"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    net_amount: Mapped[Decimal] = mapped_column(MONEY)
    vat_rate: Mapped[Decimal] = mapped_column(VAT_RATE)
    vat_amount: Mapped[Decimal] = mapped_column(
        MONEY,
        Computed("round(net_amount * vat_rate, 2)", persisted=True),
    )
    issue_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date | None] = mapped_column(Date)
    expected_payment_date: Mapped[date | None] = mapped_column(Date)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("gross_amount > 0", name="gross_amount_positive"),
        CheckConstraint(
            "input_vat_amount >= 0 AND input_vat_amount <= gross_amount",
            name="input_vat_within_gross",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    expense_date: Mapped[date] = mapped_column(Date)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY)
    input_vat_amount: Mapped[Decimal] = mapped_column(MONEY)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint("period_end > period_start", name="period_ordered"),
        CheckConstraint("vat_due >= 0", name="vat_due_non_negative"),
        CheckConstraint("forecast_vat >= 0", name="forecast_vat_non_negative"),
        CheckConstraint("proposed_amount >= 0", name="proposed_amount_non_negative"),
        CheckConstraint(
            "char_length(explanation) BETWEEN 1 AND 2000",
            name="explanation_length",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executed', 'failed', 'superseded')",
            name="status_known",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    vat_due: Mapped[Decimal] = mapped_column(MONEY)
    forecast_vat: Mapped[Decimal] = mapped_column(MONEY)
    proposed_amount: Mapped[Decimal] = mapped_column(MONEY)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 255",
            name="idempotency_key_length",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="status_known",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proposals.id"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
