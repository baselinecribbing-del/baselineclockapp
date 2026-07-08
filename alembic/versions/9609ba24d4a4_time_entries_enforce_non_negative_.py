"""time_entries enforce non negative duration

Revision ID: 9609ba24d4a4
Revises: c91d2e3f4a5b
Create Date: 2026-07-08 14:41:09.434096

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9609ba24d4a4'
down_revision: Union[str, Sequence[str], None] = 'b3d4f6a7c8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_time_entries_ended_at_after_started_at"


def upgrade() -> None:
    """Enforce non-negative time-entry duration at the DB layer.

    A completed time entry must never end before it started; active entries
    (ended_at IS NULL) are unaffected. Backs the application-layer guard in
    time_engine_v10.clock_out.
    """
    op.create_check_constraint(
        CONSTRAINT_NAME,
        "time_entries",
        "ended_at IS NULL OR ended_at >= started_at",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(CONSTRAINT_NAME, "time_entries", type_="check")
