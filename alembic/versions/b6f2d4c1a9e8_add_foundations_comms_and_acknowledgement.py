"""add foundations communication and acknowledgement workflow

Revision ID: b6f2d4c1a9e8
Revises: a5e7c2d9b4f1
Create Date: 2026-03-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b6f2d4c1a9e8"
down_revision: Union[str, Sequence[str], None] = "a5e7c2d9b4f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("crew_assignments", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("crew_assignments", sa.Column("acknowledged_by_employee_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_crew_assignments_acknowledged_by_employee",
        "crew_assignments",
        "employees",
        ["acknowledged_by_employee_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_crew_assignments_acknowledged_by_employee_id",
        "crew_assignments",
        ["acknowledged_by_employee_id"],
        unique=False,
    )

    op.create_table(
        "foundations_messages",
        sa.Column("foundations_message_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("message_type", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "message_type IN ('BROADCAST','JOB_INSTRUCTION','SAFETY_NOTICE')",
            name="ck_foundations_messages_message_type_valid",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT", name="fk_foundations_messages_job"),
        sa.ForeignKeyConstraint(["scope_id"], ["scopes.id"], ondelete="RESTRICT", name="fk_foundations_messages_scope"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT", name="fk_foundations_messages_employee"),
        sa.PrimaryKeyConstraint("foundations_message_id"),
    )
    op.create_index("ix_foundations_messages_company_id", "foundations_messages", ["company_id"], unique=False)
    op.create_index("ix_foundations_messages_job_id", "foundations_messages", ["job_id"], unique=False)
    op.create_index("ix_foundations_messages_scope_id", "foundations_messages", ["scope_id"], unique=False)
    op.create_index("ix_foundations_messages_employee_id", "foundations_messages", ["employee_id"], unique=False)
    op.create_index("ix_foundations_messages_message_type", "foundations_messages", ["message_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_foundations_messages_message_type", table_name="foundations_messages")
    op.drop_index("ix_foundations_messages_employee_id", table_name="foundations_messages")
    op.drop_index("ix_foundations_messages_scope_id", table_name="foundations_messages")
    op.drop_index("ix_foundations_messages_job_id", table_name="foundations_messages")
    op.drop_index("ix_foundations_messages_company_id", table_name="foundations_messages")
    op.drop_table("foundations_messages")

    op.drop_index("ix_crew_assignments_acknowledged_by_employee_id", table_name="crew_assignments")
    op.drop_constraint("fk_crew_assignments_acknowledged_by_employee", "crew_assignments", type_="foreignkey")
    op.drop_column("crew_assignments", "acknowledged_by_employee_id")
    op.drop_column("crew_assignments", "acknowledged_at")
