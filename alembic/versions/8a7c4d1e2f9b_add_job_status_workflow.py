"""add job status workflow

Revision ID: 8a7c4d1e2f9b
Revises: 7e4a1c2d9b6f
Create Date: 2026-03-10 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a7c4d1e2f9b"
down_revision: Union[str, Sequence[str], None] = "7e4a1c2d9b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("status", sa.String(), server_default="QUEUED", nullable=False))
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_check_constraint(
        "ck_jobs_status_valid",
        "jobs",
        "status IN ('QUEUED','UPCOMING','ACTIVE','ON_HOLD','COMPLETE')",
    )

    op.create_table(
        "job_status_transitions",
        sa.Column("job_status_transition_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("transitioned_by_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_job_status_transitions_job_id_jobs"),
        sa.PrimaryKeyConstraint("job_status_transition_id"),
    )
    op.create_index("ix_job_status_transitions_company_id", "job_status_transitions", ["company_id"], unique=False)
    op.create_index("ix_job_status_transitions_job_id", "job_status_transitions", ["job_id"], unique=False)
    op.create_index("ix_job_status_transitions_to_status", "job_status_transitions", ["to_status"], unique=False)
    op.create_index("ix_job_status_transitions_created_at", "job_status_transitions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_status_transitions_created_at", table_name="job_status_transitions")
    op.drop_index("ix_job_status_transitions_to_status", table_name="job_status_transitions")
    op.drop_index("ix_job_status_transitions_job_id", table_name="job_status_transitions")
    op.drop_index("ix_job_status_transitions_company_id", table_name="job_status_transitions")
    op.drop_table("job_status_transitions")

    op.drop_constraint("ck_jobs_status_valid", "jobs", type_="check")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_column("jobs", "status")
