"""allow superseded proposals

Revision ID: 7c1e2a9f4b10
Revises: d634bc3d2fb9
Create Date: 2026-11-05 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '7c1e2a9f4b10'
down_revision: Union[str, Sequence[str], None] = 'd634bc3d2fb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('status_known', 'proposals', type_='check')
    op.create_check_constraint(
        'status_known',
        'proposals',
        "status IN ('pending', 'approved', 'rejected', 'executed', 'failed', 'superseded')",
    )


def downgrade() -> None:
    op.execute("UPDATE proposals SET status = 'rejected' WHERE status = 'superseded'")
    op.drop_constraint('status_known', 'proposals', type_='check')
    op.create_check_constraint(
        'status_known',
        'proposals',
        "status IN ('pending', 'approved', 'rejected', 'executed', 'failed')",
    )
