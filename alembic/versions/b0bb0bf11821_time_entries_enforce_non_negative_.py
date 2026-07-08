"""time_entries enforce non negative duration

Revision ID: b0bb0bf11821
Revises: f6e5d4c3b2a1
Create Date: 2026-07-08 12:21:44.382119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0bb0bf11821'
down_revision: Union[str, Sequence[str], None] = 'f6e5d4c3b2a1'
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
