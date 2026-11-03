from datetime import date

from finance_agent.models import VATPeriod

_QUARTER_START_MONTHS = (1, 4, 7, 10)


def quarter_containing(as_of: date) -> VATPeriod:
    """Return the calendar quarter that contains as_of. period_end is exclusive."""
    start_month = _QUARTER_START_MONTHS[(as_of.month - 1) // 3]
    period_start = date(as_of.year, start_month, 1)
    if start_month == 10:
        period_end = date(as_of.year + 1, 1, 1)
    else:
        period_end = date(as_of.year, start_month + 3, 1)
    return VATPeriod(period_start=period_start, period_end=period_end)
