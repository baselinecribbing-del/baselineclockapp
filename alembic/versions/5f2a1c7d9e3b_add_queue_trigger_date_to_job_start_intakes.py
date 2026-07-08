"""add queue trigger date to job start intakes

Revision ID: 5f2a1c7d9e3b
Revises: 4c1d2e3f4a5b
Create Date: 2026-03-10 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5f2a1c7d9e3b"
down_revision: Union[str, Sequence[str], None] = "4c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_start_intakes", sa.Column("queue_trigger_date", sa.Date(), nullable=True))
    op.create_index("ix_job_start_intakes_queue_trigger_date", "job_start_intakes", ["queue_trigger_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_start_intakes_queue_trigger_date", table_name="job_start_intakes")
    op.drop_column("job_start_intakes", "queue_trigger_date")
