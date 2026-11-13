"""account as-of date and the demo's real payment dates

Revision ID: c4e8a1b07d22
Revises: 7c1e2a9f4b10
Create Date: 2026-11-13 13:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a1b07d22"
down_revision: Union[str, Sequence[str], None] = "7c1e2a9f4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EIGHT_THOUSAND = "00000000-0000-4000-8000-000000000103"
_TWO_THOUSAND = "00000000-0000-4000-8000-000000000104"


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("as_of_date", sa.Date(), server_default="2026-11-15", nullable=False),
    )
    # The demo used to store the 15 November snapshot. Keep the real payment dates
    # so a later day can see them. Leave a date someone already set untouched.
    op.execute(
        "UPDATE invoices SET payment_date = DATE '2027-01-05' "
        f"WHERE id = '{_EIGHT_THOUSAND}' AND payment_date IS NULL"
    )
    op.execute(
        "UPDATE invoices SET payment_date = DATE '2026-12-10' "
        f"WHERE id = '{_TWO_THOUSAND}' AND payment_date IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE invoices SET payment_date = NULL "
        f"WHERE id = '{_EIGHT_THOUSAND}' AND payment_date = DATE '2027-01-05'"
    )
    op.execute(
        "UPDATE invoices SET payment_date = NULL "
        f"WHERE id = '{_TWO_THOUSAND}' AND payment_date = DATE '2026-12-10'"
    )
    op.drop_column("accounts", "as_of_date")
