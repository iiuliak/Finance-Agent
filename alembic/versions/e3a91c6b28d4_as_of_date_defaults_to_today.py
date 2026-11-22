"""as_of_date defaults to today

Revision ID: e3a91c6b28d4
Revises: c4e8a1b07d22
Create Date: 2026-11-16 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a91c6b28d4"
down_revision: Union[str, Sequence[str], None] = "c4e8a1b07d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("accounts", "as_of_date", server_default=sa.text("CURRENT_DATE"))


def downgrade() -> None:
    op.alter_column("accounts", "as_of_date", server_default="2026-11-15")
