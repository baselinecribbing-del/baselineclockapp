"""add job start intake promotion linkage

Revision ID: 6c8f4e2a1b7d
Revises: 5f2a1c7d9e3b
Create Date: 2026-03-10 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6c8f4e2a1b7d"
down_revision: Union[str, Sequence[str], None] = "5f2a1c7d9e3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_start_intakes",
        sa.Column("promotion_status", sa.String(), server_default="NOT_PROMOTED", nullable=False),
    )
    op.add_column("job_start_intakes", sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_job_start_intakes_promotion_status_valid",
        "job_start_intakes",
        "promotion_status IN ('NOT_PROMOTED','PROMOTED')",
    )
    op.create_index(
        "ix_job_start_intakes_promotion_status",
        "job_start_intakes",
        ["promotion_status"],
        unique=False,
    )

    op.add_column("jobs", sa.Column("source_job_start_intake_id", sa.String(), nullable=True))
    op.create_index("ix_jobs_source_job_start_intake_id", "jobs", ["source_job_start_intake_id"], unique=True)
    op.create_foreign_key(
        "fk_jobs_source_job_start_intake_id",
        "jobs",
        "job_start_intakes",
        ["source_job_start_intake_id"],
        ["job_start_intake_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_source_job_start_intake_id", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_source_job_start_intake_id", table_name="jobs")
    op.drop_column("jobs", "source_job_start_intake_id")

    op.drop_index("ix_job_start_intakes_promotion_status", table_name="job_start_intakes")
    op.drop_constraint("ck_job_start_intakes_promotion_status_valid", "job_start_intakes", type_="check")
    op.drop_column("job_start_intakes", "promoted_at")
    op.drop_column("job_start_intakes", "promotion_status")
