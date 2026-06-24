"""add foundation activity log

Revision ID: c3d8a1f5e2b7
Revises: b6f2d4c1a9e8
Create Date: 2026-03-07 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d8a1f5e2b7"
down_revision: Union[str, Sequence[str], None] = "b6f2d4c1a9e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "foundation_activity_log",
        sa.Column("foundation_activity_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("activity_type", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("photo_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "activity_type IN ('CLOCK_IN','CLOCK_OUT','JOB_PROGRESS_PHOTO','SITE_NOTE','ISSUE_REPORTED')",
            name="ck_foundation_activity_log_activity_type_valid",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_foundation_activity_log_job"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT", name="fk_foundation_activity_log_scope"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT", name="fk_foundation_activity_log_employee"),
        sa.PrimaryKeyConstraint("foundation_activity_id"),
    )

    op.create_index("ix_foundation_activity_log_company_id", "foundation_activity_log", ["company_id"], unique=False)
    op.create_index("ix_foundation_activity_log_job_id", "foundation_activity_log", ["job_id"], unique=False)
    op.create_index("ix_foundation_activity_log_scope_id", "foundation_activity_log", ["scope_id"], unique=False)
    op.create_index("ix_foundation_activity_log_employee_id", "foundation_activity_log", ["employee_id"], unique=False)
    op.create_index("ix_foundation_activity_log_activity_type", "foundation_activity_log", ["activity_type"], unique=False)
    op.create_index("ix_foundation_activity_log_created_at", "foundation_activity_log", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_foundation_activity_log_created_at", table_name="foundation_activity_log")
    op.drop_index("ix_foundation_activity_log_activity_type", table_name="foundation_activity_log")
    op.drop_index("ix_foundation_activity_log_employee_id", table_name="foundation_activity_log")
    op.drop_index("ix_foundation_activity_log_scope_id", table_name="foundation_activity_log")
    op.drop_index("ix_foundation_activity_log_job_id", table_name="foundation_activity_log")
    op.drop_index("ix_foundation_activity_log_company_id", table_name="foundation_activity_log")
    op.drop_table("foundation_activity_log")
