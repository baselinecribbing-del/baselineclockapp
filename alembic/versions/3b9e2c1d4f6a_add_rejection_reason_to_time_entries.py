"""add rejection_reason to time_entries

Revision ID: 3b9e2c1d4f6a
Revises: 2c9d4e7f1a2b
Create Date: 2026-03-09 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3b9e2c1d4f6a"
down_revision: Union[str, Sequence[str], None] = "2c9d4e7f1a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("time_entries", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE time_entries
        SET rejection_reason = approval_note
        WHERE approval_status = 'rejected'
          AND approval_note IS NOT NULL
          AND rejection_reason IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("time_entries", "rejection_reason")
