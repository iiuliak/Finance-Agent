from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finance_agent.agent.template import answer
from finance_agent.agent.when import parse_when, resolve_when
from finance_agent.demo_data import DEMO_ACCOUNT_ID
from finance_agent.seed import seed

TODAY = date(2026, 11, 15)


def test_may_as_a_verb_is_not_a_month() -> None:
    found = parse_when("May I see the invoices?", TODAY)

    assert found.named is False


def test_this_quarter_is_the_quarter_of_the_page_day() -> None:
    found = parse_when("I want only the invoices for this quarter", TODAY)
    view = resolve_when(found, TODAY)

    assert found.start == date(2026, 10, 1)
    assert found.end == date(2027, 1, 1)
    assert view.list_as_of == TODAY
    assert view.vat_as_of == TODAY
    assert view.label == "October–December 2026"


def test_a_month_a_range_and_a_named_day() -> None:
    august = parse_when("expenses in August 2026", TODAY)
    span = parse_when("invoices from 1 April 2026 to 30 June 2026", TODAY)
    point = parse_when("What was the VAT as of 10 December 2026?", TODAY)
    standing = resolve_when(point, TODAY)

    assert august.start == date(2026, 8, 1)
    assert august.end == date(2026, 9, 1)
    assert span.start == date(2026, 4, 1)
    assert span.end == date(2026, 7, 1)
    assert point.point == date(2026, 12, 10)
    assert point.start is None
    assert standing.vat_as_of == date(2026, 12, 10)
    assert standing.period.period_start == date(2026, 10, 1)


def test_last_window_in_the_message_wins() -> None:
    found = parse_when("Not Q1. Show me Q3 2026.", TODAY)
    later = parse_when("Not this quarter. August.", TODAY)

    assert found.start == date(2026, 7, 1)
    assert found.end == date(2026, 10, 1)
    assert later.start == date(2026, 8, 1)
    assert later.end == date(2026, 9, 1)


def test_current_period_and_previous_quarter_stay_apart(db_session: Session) -> None:
    seed(db_session)

    reply, _proposal = answer(
        db_session,
        DEMO_ACCOUNT_ID,
        "give ne invoices for current period and expenses for previous quarter",
    )
    invoices, expenses = reply.split("**Expenses", 1)

    assert "October–December 2026" in invoices
    assert "€10,000.00" in invoices
    assert "€12,000.00" not in invoices
    assert "July–September 2026" in expenses
    assert "10 July 2026" in expenses
    assert "10 October 2026" not in expenses


def test_a_span_of_months_is_its_own_window(db_session: Session) -> None:
    seed(db_session)

    march, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "invoices from March to May")
    listed, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "expenses in March and April")
    recent, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "invoices for the last 3 months")

    assert "March–May 2026" in march
    assert "€7,000.00" in march
    assert "€11,000.00" in march
    assert "€6,000.00" not in march
    assert "March–April 2026" in listed
    assert "September–November 2026" in recent
    assert "€10,000.00" in recent
    assert "€12,000.00" not in recent


def test_invoices_and_expenses_keep_their_own_quarters(db_session: Session) -> None:
    seed(db_session)

    reply, proposal = answer(
        db_session,
        DEMO_ACCOUNT_ID,
        "show my invoices for the previous quarter and my expenses for current quarter",
    )
    invoices, expenses = reply.split("**Expenses", 1)

    assert proposal is None
    assert "July–September 2026" in invoices
    assert "€12,000.00" in invoices
    assert "€10,000.00" not in invoices
    assert "October–December 2026" in expenses
    assert "10 October 2026" in expenses
    assert "10 July 2026" not in expenses


def test_this_quarter_lists_only_that_quarter(db_session: Session) -> None:
    seed(db_session)

    reply, proposal = answer(db_session, DEMO_ACCOUNT_ID, "Show the invoices for this quarter")

    assert proposal is None
    assert "€10,000.00" in reply
    assert "€8,000.00" in reply
    assert "€6,000.00" not in reply
    assert "1 January 2026" not in reply
    assert "\n" in reply


def test_a_follow_up_keeps_the_subject(db_session: Session) -> None:
    seed(db_session)

    reply, _proposal = answer(
        db_session,
        DEMO_ACCOUNT_ID,
        "only August",
        [("user", "What expenses are on the books?"), ("assistant", "Here they are.")],
    )

    assert "1 August 2026" in reply
    assert "10 July 2026" not in reply
    assert "10 October 2026" not in reply
    assert "Expenses in August 2026" in reply


def test_vat_on_a_named_day_shows_the_balance_and_the_lines(db_session: Session) -> None:
    seed(db_session)

    reply, proposal = answer(db_session, DEMO_ACCOUNT_ID, "Explain the VAT as of 10 December 2026")

    assert proposal is None
    assert "10 December 2026" in reply
    assert "€2,945.00" in reply
    assert "Collected **€3,230.00**" in reply
    assert "€380.00 from the €2,000.00 invoice issued 10 November 2026, paid on 10 December 2026" in reply
    assert "€190.00 on 10 October 2026" in reply
    assert "€3,230.00 collected − €285.00 input VAT = €2,945.00." in reply
    assert "on the books today" in reply
    assert "earlier days" not in reply


def test_vat_today_still_reports_the_reserve(db_session: Session) -> None:
    seed(db_session)

    reply, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "How much VAT do I owe?")

    assert "€2,565.00" in reply
    assert "€1,900.00 from the €10,000.00 invoice" in reply
    assert "€950.00 from the €5,000.00 invoice" in reply
    assert "€190.00 on 10 October 2026" in reply
    assert "€95.00 on 1 November 2026" in reply
    assert "still owed" in reply
    assert "less than the estimated €4,085.00" in reply
    assert "Moving €3,585.00" in reply
    assert "Shall I set it aside?" in reply


def test_a_yes_after_the_vat_offer_prepares_the_transfer(db_session: Session) -> None:
    seed(db_session)

    reply, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "How much VAT do I owe?")
    _follow, proposal = answer(
        db_session,
        DEMO_ACCOUNT_ID,
        "yes",
        [("assistant", reply)],
    )

    assert proposal is not None
    assert proposal.proposed_amount == Decimal("3585.00")


def test_balance_and_vat_in_one_question_keeps_both(db_session: Session) -> None:
    seed(db_session)

    reply, proposal = answer(
        db_session,
        DEMO_ACCOUNT_ID,
        "What is my balance, and how much VAT do I owe?",
    )

    assert proposal is None
    assert "€12,000.00" in reply
    assert "€500.00" in reply
    assert "€2,565.00" in reply


def test_german_and_short_phrases_use_the_same_answers(db_session: Session) -> None:
    seed(db_session)

    vat, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "Wie viel Umsatzsteuer schulde ich?")
    invoices, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "Zeig die Rechnungen")
    owed, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "How much is owed?")
    outstanding, _proposal = answer(db_session, DEMO_ACCOUNT_ID, "What is outstanding?")

    assert "€2,565.00" in vat
    assert "Shall I set it aside?" in vat
    assert "**Invoices**" in invoices
    assert "€10,000.00" in invoices
    assert "€2,565.00" in owed
    assert "unpaid" in outstanding
    assert "€8,000.00" in outstanding
