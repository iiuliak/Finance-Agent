from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finance_agent import demo_data
from finance_agent.domain.forecast import forecast_vat
from finance_agent.domain.money import money
from finance_agent.domain.periods import quarter_containing
from finance_agent.domain.vat import calculate_vat
from finance_agent.models import ExpenseRead, InvoiceRead
from finance_agent.settings import get_settings


@dataclass(frozen=True)
class ForecastError:
    as_of: date
    estimated_vat_due: Decimal
    true_vat_due: Decimal
    absolute_error: Decimal


def evaluate(as_of: date | None = None) -> ForecastError:
    """Score the forecast against the quarter-end VAT from the true payment dates."""
    as_of = get_settings().as_of_date if as_of is None else as_of
    invoices = [
        InvoiceRead(
            id=invoice.id,
            account_id=demo_data.DEMO_ACCOUNT_ID,
            net_amount=invoice.net_amount,
            vat_rate=demo_data.VAT_RATE,
            vat_amount=money(invoice.net_amount * demo_data.VAT_RATE),
            issue_date=invoice.issue_date,
            payment_date=invoice.true_payment_date,
            expected_payment_date=invoice.expected_payment_date,
        )
        for invoice in demo_data.INVOICES
    ]
    expenses = [
        ExpenseRead(
            id=expense.id,
            account_id=demo_data.DEMO_ACCOUNT_ID,
            expense_date=expense.expense_date,
            gross_amount=expense.gross_amount,
            input_vat_amount=expense.input_vat_amount,
        )
        for expense in demo_data.EXPENSES
    ]
    period = quarter_containing(as_of)
    estimated = forecast_vat(period, as_of, invoices, expenses).estimated_vat_due
    true_vat = calculate_vat(period, invoices, expenses).vat_due
    return ForecastError(
        as_of=as_of,
        estimated_vat_due=estimated,
        true_vat_due=true_vat,
        absolute_error=abs(estimated - true_vat),
    )


def main() -> None:
    result = evaluate()
    print(f"as_of {result.as_of.isoformat()}")
    print(f"estimated_vat_due {result.estimated_vat_due}")
    print(f"true_vat_due {result.true_vat_due}")
    print(f"absolute_error {result.absolute_error}")


if __name__ == "__main__":
    main()
