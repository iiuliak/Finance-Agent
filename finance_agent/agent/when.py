"""A quarter, month, year, day, or range named in a user message.

The page's day stays the clock. A named day is the only way to stand on
another day, including one that has not arrived yet.
"""

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from finance_agent.domain.periods import quarter_containing
from finance_agent.models import VATPeriod

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_NUMBER = {name.lower(): index for index, name in enumerate(_MONTHS, start=1)}
for _name, _index in list(_MONTH_NUMBER.items()):
    _MONTH_NUMBER[_name[:3]] = _index
_MONTH_NUMBER["sept"] = 9

_MONTH_WORD = (
    "january|february|march|april|may|june|july|august|september|sept|"
    "october|november|december|jan|feb|mar|apr|jun|jul|aug|oct|nov|dec"
)
_DAY = (
    rf"(?:20\d{{2}}-\d{{2}}-\d{{2}}|\d{{1,2}}\s+(?:{_MONTH_WORD})(?:\s+20\d{{2}})?"
    rf"|(?:{_MONTH_WORD})\s+\d{{1,2}},?\s+20\d{{2}})"
)
_RANGE = re.compile(
    rf"\b(?:from|between)\s+({_DAY}|{_MONTH_WORD}(?:\s+20\d{{2}})?)\s+"
    rf"(?:to|and|until|through)\s+({_DAY}|{_MONTH_WORD}(?:\s+20\d{{2}})?)",
    re.IGNORECASE,
)
_POINT = re.compile(rf"\b(as\s+of|as\s+at|on|by|for)\s+({_DAY})\b", re.IGNORECASE)
_QUARTER = re.compile(
    r"\b(?:(this|current|last|previous|next)\s+(?:quarter|period)|"
    r"(first|second|third|fourth|1st|2nd|3rd|4th)\s+(?:quarter|period)(?:\s+(20\d{2}))?|"
    r"q([1-4])(?:\s+(20\d{2}))?|(20\d{2})\s*q([1-4]))\b",
    re.IGNORECASE,
)
_NUMBER = r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
_COUNT = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_LAST_N_MONTHS = re.compile(rf"\b(?:last|past|previous)\s+({_NUMBER})\s+months?\b", re.IGNORECASE)
_MONTH_SPAN = re.compile(
    rf"\b({_MONTH_WORD})(?:\s+(20\d{{2}}))?\s+(?:to|through|until)\s+"
    rf"({_MONTH_WORD})(?:\s+(20\d{{2}}))?\b",
    re.IGNORECASE,
)
_MONTH_LIST = re.compile(
    rf"\b({_MONTH_WORD})(?:\s+(20\d{{2}}))?(?:\s*,\s*(?:{_MONTH_WORD})(?:\s+20\d{{2}})?)*"
    rf"\s+and\s+(?:{_MONTH_WORD})(?:\s+20\d{{2}})?\b",
    re.IGNORECASE,
)
_BARE_MONTH = (
    "january|february|march|april|june|july|august|september|sept|"
    "october|november|december|jan|feb|mar|apr|jun|jul|aug|oct|nov|dec"
)
_MONTH = re.compile(
    rf"\b(?:in|for|during|throughout|over|only|just)\s+({_MONTH_WORD})(?:\s+(20\d{{2}}))?\b"
    rf"|(?<!\d )(?<!\d\d )({_MONTH_WORD})\s+(20\d{{2}})\b"
    rf"|\b({_BARE_MONTH})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:in|for|during)\s+(20\d{2})\b|\bthis\s+year\b", re.IGNORECASE)
_RELATIVE_MONTH = re.compile(r"\b(this|last|previous|next)\s+month\b", re.IGNORECASE)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


@dataclass(frozen=True)
class When:
    """What the message named. Empty fields mean the page's day and no filter."""

    start: date | None = None
    end: date | None = None
    point: date | None = None
    label: str | None = None
    # "as of 10 December" stands on that day. "on 10 December" also filters to it.
    point_only: bool = False

    @property
    def named(self) -> bool:
        return self.start is not None or self.point is not None


@dataclass(frozen=True)
class View:
    """The day the lists use, the day the VAT figure stands on, and the quarter."""

    list_as_of: date
    vat_as_of: date
    period: VATPeriod
    start: date | None
    end: date | None
    label: str | None


_SUBJECT = re.compile(r"\b(invoices?|expenses?|vat|tax)\b", re.IGNORECASE)


def mentions_when(message: str) -> bool:
    return parse_when(message, date(2026, 6, 15)).named


def view_for(message: str, today: date, kind: str) -> View:
    """The window for one subject. Two periods in one sentence stay with their own list."""
    periods = _all_periods(message, today)
    subjects = _subject_spans(message)
    if len(periods) >= 2 and len({item[2] for item in subjects}) >= 2:
        chosen = _assign(periods, subjects).get(kind, When())
        return resolve_when(chosen, today)
    return resolve_when(parse_when(message, today), today)


def parse_when(message: str, today: date) -> When:
    """The last range in the message wins. A named day is kept alongside it."""
    # The period named last is the one the user settled on.
    # (end, length, window). A longer span wins when it ends in the same place as a single month.
    candidates: list[tuple[int, int, When]] = []
    ranged = _last(_RANGE.finditer(message))
    if ranged is not None:
        parsed = _range_when(ranged.group(1), ranged.group(2), today)
        if parsed is not None:
            candidates.append((ranged.end(), ranged.end() - ranged.start(), parsed))
    if (quarter := _last(_QUARTER.finditer(message))) is not None:
        candidates.append((quarter.end(), quarter.end() - quarter.start(), _quarter_when(quarter, today)))
    if (month := _last(_RELATIVE_MONTH.finditer(message))) is not None:
        candidates.append((month.end(), month.end() - month.start(), _relative_month(month.group(1).lower(), today)))
    if (month := _month_outside_a_day(message)) is not None:
        token = month.group(1) or month.group(3) or month.group(5)
        year = int(month.group(2) or month.group(4) or today.year)
        candidates.append((month.end(), month.end() - month.start(), _span(*_month_bounds(year, _month_number(token)))))
    if (year := _last(_YEAR.finditer(message))) is not None:
        number = int(year.group(1) or today.year)
        candidates.append((year.end(), year.end() - year.start(), _span(date(number, 1, 1), date(number + 1, 1, 1), str(number))))
    if (counted := _last(_LAST_N_MONTHS.finditer(message))) is not None:
        candidates.append((counted.end(), counted.end() - counted.start(), _last_n_months(_count(counted.group(1)), today)))
    if (span := _last(_MONTH_SPAN.finditer(message))) is not None:
        candidates.append((span.end(), span.end() - span.start(), _months_when(span.group(0), today)))
    if (listed := _last(_MONTH_LIST.finditer(message))) is not None:
        candidates.append((listed.end(), listed.end() - listed.start(), _months_when(listed.group(0), today)))
    found = max(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else When()

    pointed = _last(_POINT.finditer(message))
    if pointed is None:
        return found
    day = _parse_day(pointed.group(2), today)
    if day is None:
        return found
    phrase = pointed.group(1).lower()
    point_only = phrase.startswith("as") or phrase == "by"
    if found.start is None and not point_only:
        return When(start=day, end=day + timedelta(days=1), point=day, label=_day_label(day))
    return When(start=found.start, end=found.end, point=day, label=found.label, point_only=point_only)


def resolve_when(when: When, today: date) -> View:
    """Lists follow the page until a day is named. A finished window is read at its end."""
    list_as_of = when.point or today
    vat_as_of = list_as_of
    if when.point is None and when.end is not None:
        last = when.end - timedelta(days=1)
        if last < today:
            vat_as_of = last
    period = quarter_containing(vat_as_of)
    if _covers_quarter(when.start, when.end):
        period = quarter_containing(when.start)
        if when.point is None:
            last = when.end - timedelta(days=1)
            vat_as_of = today if period.period_start <= today <= last else last
            if today < period.period_start:
                vat_as_of = today
    label = when.label or (_quarter_label(period) if when.named else None)
    return View(list_as_of, vat_as_of, period, when.start, when.end, label)


def quarter_label(period: VATPeriod) -> str:
    return _quarter_label(period)


def _range_when(left: str, right: str, today: date) -> When | None:
    start, start_month = _edge(left, today, end=False)
    finish, finish_month = _edge(right, today, end=True)
    if start is None or finish is None:
        return None
    if start_month and finish_month and finish <= start:
        finish = _shift_year(finish, 1)
    elif not start_month and finish <= start:
        return None
    if start_month and finish_month:
        label = _span_label(start, finish)
    else:
        label = f"{_edge_label(left, today)} to {_edge_label(right, today)}"
    return _span(start, finish, label)


def _edge(text: str, today: date, end: bool) -> tuple[date | None, bool]:
    day = _parse_day(text, today)
    if day is not None and re.search(r"\d", text):
        if re.fullmatch(rf"(?:{_MONTH_WORD})(?:\s+20\d{{2}})?", text.strip(), re.IGNORECASE):
            year, month = _month_of(text, today)
            start, finish = _month_bounds(year, month)
            return (finish if end else start), True
        return (day + timedelta(days=1) if end else day), False
    if re.fullmatch(rf"(?:{_MONTH_WORD})(?:\s+20\d{{2}})?", text.strip(), re.IGNORECASE):
        year, month = _month_of(text, today)
        start, finish = _month_bounds(year, month)
        return (finish if end else start), True
    return None, False


def _edge_label(text: str, today: date) -> str:
    if re.fullmatch(rf"(?:{_MONTH_WORD})(?:\s+20\d{{2}})?", text.strip(), re.IGNORECASE):
        year, month = _month_of(text, today)
        return f"{_MONTHS[month - 1]} {year}"
    day = _parse_day(text, today)
    return _day_label(day) if day is not None else text.strip()


def _quarter_when(match: re.Match[str], today: date) -> When:
    relative, ordinal, ordinal_year, q_number, q_year, year_first, year_first_q = match.groups()
    if relative:
        shift = {"this": 0, "current": 0, "last": -1, "previous": -1, "next": 1}[relative.lower()]
        period = _shift_quarter(quarter_containing(today), shift)
    elif ordinal:
        number = _ORDINAL[ordinal.lower()]
        year = int(ordinal_year or today.year)
        period = quarter_containing(date(year, number * 3 - 2, 1))
    elif year_first:
        period = quarter_containing(date(int(year_first), int(year_first_q) * 3 - 2, 1))
    else:
        period = quarter_containing(date(int(q_year or today.year), int(q_number) * 3 - 2, 1))
    return _span(period.period_start, period.period_end, _quarter_label(period))


def _count(token: str) -> int:
    try:
        return int(token)
    except ValueError:
        return _COUNT[token.lower()]


def _last_n_months(count: int, today: date) -> When:
    """The current month and the ones before it. One month means the previous month."""
    if count <= 1:
        return _relative_month("last", today)
    year, month = _add_months(today.year, today.month, -(count - 1))
    start = date(year, month, 1)
    end = _month_after(date(today.year, today.month, 1))
    return _span(start, end, _span_label(start, end))


def _months_when(text: str, today: date) -> When:
    months = [
        (int(match.group(2) or today.year), _month_number(match.group(1)))
        for match in re.finditer(rf"({_MONTH_WORD})(?:\s+(20\d{{2}}))?", text, re.IGNORECASE)
    ]
    start_year, start_month = months[0]
    end_year, end_month = months[-1]
    if (end_year, end_month) < (start_year, start_month):
        end_year += 1
    start = date(start_year, start_month, 1)
    end = _month_after(date(end_year, end_month, 1))
    return _span(start, end, _span_label(start, end))


def _span_label(start: date, end: date) -> str:
    last = end - timedelta(days=1)
    if start.year == last.year and start.month == last.month:
        return f"{_MONTHS[start.month - 1]} {start.year}"
    if start.year == last.year:
        return f"{_MONTHS[start.month - 1]}–{_MONTHS[last.month - 1]} {start.year}"
    return f"{_MONTHS[start.month - 1]} {start.year}–{_MONTHS[last.month - 1]} {last.year}"


def _relative_month(which: str, today: date) -> When:
    shift = {"this": 0, "last": -1, "previous": -1, "next": 1}[which]
    year, month = _add_months(today.year, today.month, shift)
    return _span(*_month_bounds(year, month))


def _span(start: date, end: date, label: str | None = None) -> When:
    if label is None and start.day == 1 and end == _month_after(start):
        label = f"{_MONTHS[start.month - 1]} {start.year}"
    return When(start=start, end=end, label=label)


def _parse_day(text: str, today: date) -> date | None:
    token = " ".join(text.strip().replace(",", " ").split())
    iso = re.fullmatch(r"(20\d{2})-(\d{2})-(\d{2})", token)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    written = re.fullmatch(rf"(\d{{1,2}})\s+({_MONTH_WORD})(?:\s+(20\d{{2}}))?", token, re.IGNORECASE)
    if written:
        return _safe_date(int(written.group(3) or today.year), _month_number(written.group(2)), int(written.group(1)))
    month_first = re.fullmatch(rf"({_MONTH_WORD})\s+(\d{{1,2}})(?:\s+(20\d{{2}}))?", token, re.IGNORECASE)
    if month_first:
        return _safe_date(
            int(month_first.group(3) or today.year),
            _month_number(month_first.group(1)),
            int(month_first.group(2)),
        )
    return None


def _month_of(text: str, today: date) -> tuple[int, int]:
    match = re.fullmatch(rf"({_MONTH_WORD})(?:\s+(20\d{{2}}))?", text.strip(), re.IGNORECASE)
    assert match is not None
    return int(match.group(2) or today.year), _month_number(match.group(1))


def _month_number(token: str) -> int:
    return _MONTH_NUMBER[token.lower()]


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    return start, _month_after(start)


def _month_after(start: date) -> date:
    year, month = _add_months(start.year, start.month, 1)
    return date(year, month, 1)


def _add_months(year: int, month: int, shift: int) -> tuple[int, int]:
    month += shift
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return year, month


def _shift_quarter(period: VATPeriod, shift: int) -> VATPeriod:
    year, month = _add_months(period.period_start.year, period.period_start.month, shift * 3)
    return quarter_containing(date(year, month, 1))


def _shift_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=monthrange(value.year + years, value.month)[1])


def _covers_quarter(start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return False
    period = quarter_containing(start)
    return period.period_start == start and period.period_end == end


def _quarter_label(period: VATPeriod) -> str:
    start = period.period_start
    last = period.period_end - timedelta(days=1)
    if start.year == last.year:
        return f"{_MONTHS[start.month - 1]}–{_MONTHS[last.month - 1]} {start.year}"
    return f"{_MONTHS[start.month - 1]} {start.year}–{_MONTHS[last.month - 1]} {last.year}"


def _day_label(value: date) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _all_periods(message: str, today: date) -> list[tuple[int, int, When]]:
    found: list[tuple[int, int, When]] = []
    for match in _RANGE.finditer(message):
        parsed = _range_when(match.group(1), match.group(2), today)
        if parsed is not None:
            found.append((match.start(), match.end(), parsed))
    for match in _QUARTER.finditer(message):
        found.append((match.start(), match.end(), _quarter_when(match, today)))
    for match in _RELATIVE_MONTH.finditer(message):
        found.append((match.start(), match.end(), _relative_month(match.group(1).lower(), today)))
    for match in _MONTH.finditer(message):
        if _inside_a_day(match, message):
            continue
        token = match.group(1) or match.group(3) or match.group(5)
        year = int(match.group(2) or match.group(4) or today.year)
        found.append((match.start(), match.end(), _span(*_month_bounds(year, _month_number(token)))))
    for match in _YEAR.finditer(message):
        number = int(match.group(1) or today.year)
        found.append((match.start(), match.end(), _span(date(number, 1, 1), date(number + 1, 1, 1), str(number))))
    for match in _LAST_N_MONTHS.finditer(message):
        found.append((match.start(), match.end(), _last_n_months(_count(match.group(1)), today)))
    for match in _MONTH_SPAN.finditer(message):
        found.append((match.start(), match.end(), _months_when(match.group(0), today)))
    for match in _MONTH_LIST.finditer(message):
        found.append((match.start(), match.end(), _months_when(match.group(0), today)))
    for match in _POINT.finditer(message):
        day = _parse_day(match.group(2), today)
        if day is None:
            continue
        phrase = match.group(1).lower()
        point_only = phrase.startswith("as") or phrase == "by"
        if point_only:
            found.append((match.start(), match.end(), When(point=day, point_only=True)))
        else:
            found.append(
                (
                    match.start(),
                    match.end(),
                    When(start=day, end=day + timedelta(days=1), point=day, label=_day_label(day)),
                )
            )
    return _without_overlaps(found)


def _subject_spans(message: str) -> list[tuple[int, int, str]]:
    spans = []
    for match in _SUBJECT.finditer(message):
        word = match.group(1).lower()
        if word.startswith("inv"):
            kind = "invoice"
        elif word.startswith("exp"):
            kind = "expense"
        else:
            kind = "vat"
        spans.append((match.start(), match.end(), kind))
    return spans


def _assign(periods: list[tuple[int, int, When]], subjects: list[tuple[int, int, str]]) -> dict[str, When]:
    assigned: dict[str, When] = {}
    for start, end, when in sorted(periods, key=lambda item: item[0]):
        assigned[_nearest(start, end, subjects)] = when
    return assigned


def _nearest(start: int, end: int, subjects: list[tuple[int, int, str]]) -> str:
    """A period belongs to the subject just before it: 'invoices for the previous quarter'."""
    before = [subject for subject in subjects if subject[1] <= start]
    if before:
        return max(before, key=lambda subject: subject[1])[2]
    after = [subject for subject in subjects if subject[0] >= end]
    if after:
        return min(after, key=lambda subject: subject[0])[2]
    return subjects[0][2]


def _inside_a_day(match: re.Match[str], message: str) -> bool:
    covered = [(item.start(), item.end()) for item in re.finditer(_DAY, message, re.IGNORECASE)]
    return any(start <= match.start() and match.end() <= end for start, end in covered)


def _without_overlaps(found: list[tuple[int, int, When]]) -> list[tuple[int, int, When]]:
    ordered = sorted(found, key=lambda item: (item[0], item[0] - item[1]))
    kept: list[tuple[int, int, When]] = []
    for start, end, when in ordered:
        if any(kept_start <= start and end <= kept_end for kept_start, kept_end, _when in kept):
            continue
        kept.append((start, end, when))
    return kept


def _month_outside_a_day(message: str) -> re.Match[str] | None:
    """A month written inside '10 December 2026' is part of that day, not a filter."""
    covered = [(match.start(), match.end()) for match in re.finditer(_DAY, message, re.IGNORECASE)]
    found: re.Match[str] | None = None
    for match in _MONTH.finditer(message):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        found = match
    return found


def _last(matches: object) -> re.Match[str] | None:
    found: re.Match[str] | None = None
    for match in matches:  # type: ignore[union-attr]
        found = match
    return found
