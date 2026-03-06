"""add time entry approval fields

Revision ID: 9c7e6a1b4d21
Revises: e1943f73e695
Create Date: 2026-03-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c7e6a1b4d21"
down_revision: Union[str, Sequence[str], None] = "e1943f73e695"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "time_entries",
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
    )
    op.add_column("time_entries", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("time_entries", sa.Column("approved_by_user_id", sa.String(), nullable=True))
    op.add_column("time_entries", sa.Column("rejected_at", sa.DateTime(), nullable=True))
    op.add_column("time_entries", sa.Column("rejected_by_user_id", sa.String(), nullable=True))
    op.add_column("time_entries", sa.Column("approval_note", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_time_entries_approval_status_allowed",
        "time_entries",
        "approval_status in ('pending', 'approved', 'rejected')",
    )
    op.create_index(
        "ix_time_entries_company_id_approval_status",
        "time_entries",
        ["company_id", "approval_status"],
        unique=False,
    )

    op.alter_column("time_entries", "approval_status", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_time_entries_company_id_approval_status", table_name="time_entries")
    op.drop_constraint("ck_time_entries_approval_status_allowed", "time_entries", type_="check")
    op.drop_column("time_entries", "approval_note")
    op.drop_column("time_entries", "rejected_by_user_id")
    op.drop_column("time_entries", "rejected_at")
    op.drop_column("time_entries", "approved_by_user_id")
    op.drop_column("time_entries", "approved_at")
    op.drop_column("time_entries", "approval_status")
