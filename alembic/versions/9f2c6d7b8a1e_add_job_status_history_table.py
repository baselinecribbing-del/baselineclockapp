"""add job status history table

Revision ID: 9f2c6d7b8a1e
Revises: 8a7c4d1e2f9b
Create Date: 2026-03-10 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f2c6d7b8a1e"
down_revision: Union[str, Sequence[str], None] = "8a7c4d1e2f9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_job_status_history_job_id_jobs"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_status_history_company_id", "job_status_history", ["company_id"], unique=False)
    op.create_index("ix_job_status_history_job_id", "job_status_history", ["job_id"], unique=False)
    op.create_index("ix_job_status_history_to_status", "job_status_history", ["to_status"], unique=False)
    op.create_index("ix_job_status_history_changed_at", "job_status_history", ["changed_at"], unique=False)
    op.create_index(
        "ix_job_status_history_job_id_changed_at_id",
        "job_status_history",
        ["job_id", "changed_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_status_history_job_id_changed_at_id", table_name="job_status_history")
    op.drop_index("ix_job_status_history_changed_at", table_name="job_status_history")
    op.drop_index("ix_job_status_history_to_status", table_name="job_status_history")
    op.drop_index("ix_job_status_history_job_id", table_name="job_status_history")
    op.drop_index("ix_job_status_history_company_id", table_name="job_status_history")
    op.drop_table("job_status_history")
