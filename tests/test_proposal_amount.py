from decimal import Decimal

from finance_agent.domain.proposal import proposed_reserve_transfer


def test_seed_proposal_is_3585() -> None:
    amount = proposed_reserve_transfer(
        estimated_vat_due=Decimal("4085.00"),
        operating_balance=Decimal("12000.00"),
        reserve_balance=Decimal("500.00"),
    )

    assert amount == Decimal("3585.00")


def test_reserve_that_already_covers_the_estimate_proposes_zero() -> None:
    amount = proposed_reserve_transfer(
        estimated_vat_due=Decimal("4085.00"),
        operating_balance=Decimal("12000.00"),
        reserve_balance=Decimal("4085.00"),
    )

    assert amount == Decimal("0.00")


def test_proposal_is_capped_by_the_operating_balance() -> None:
    amount = proposed_reserve_transfer(
        estimated_vat_due=Decimal("4085.00"),
        operating_balance=Decimal("100.00"),
        reserve_balance=Decimal("500.00"),
    )

    assert amount == Decimal("100.00")


def test_zero_estimate_and_zero_reserve_proposes_zero() -> None:
    amount = proposed_reserve_transfer(
        estimated_vat_due=Decimal("0.00"),
        operating_balance=Decimal("12000.00"),
        reserve_balance=Decimal("0.00"),
    )

    assert amount == Decimal("0.00")
