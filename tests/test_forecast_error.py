from datetime import date
from decimal import Decimal

from finance_agent.eval_forecast import evaluate


def test_forecast_error_on_the_demo_quarter() -> None:
    result = evaluate(date(2026, 11, 15))

    assert result.estimated_vat_due == Decimal("4085.00")
    assert result.true_vat_due == Decimal("2945.00")
    assert result.absolute_error == Decimal("1140.00")
