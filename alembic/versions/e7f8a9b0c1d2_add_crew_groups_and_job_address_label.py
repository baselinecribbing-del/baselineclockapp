"""add crew groups and job address label

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-03-07 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("address_label", sa.String(), nullable=True))
    op.create_index("ix_jobs_address_label", "jobs", ["address_label"], unique=False)

    op.create_table(
        "crew_groups",
        sa.Column("crew_group_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("crew_group_id"),
    )
    op.create_index("ix_crew_groups_company_id", "crew_groups", ["company_id"], unique=False)
    op.create_index("ix_crew_groups_name", "crew_groups", ["name"], unique=False)
    op.create_index("ix_crew_groups_created_at", "crew_groups", ["created_at"], unique=False)

    op.create_table(
        "crew_group_members",
        sa.Column("crew_group_member_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("crew_group_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["crew_group_id"], ["crew_groups.crew_group_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("crew_group_member_id"),
        sa.UniqueConstraint(
            "company_id",
            "crew_group_id",
            "employee_id",
            name="uq_crew_group_members_company_group_employee",
        ),
    )
    op.create_index("ix_crew_group_members_company_id", "crew_group_members", ["company_id"], unique=False)
    op.create_index("ix_crew_group_members_crew_group_id", "crew_group_members", ["crew_group_id"], unique=False)
    op.create_index("ix_crew_group_members_employee_id", "crew_group_members", ["employee_id"], unique=False)
    op.create_index("ix_crew_group_members_created_at", "crew_group_members", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_crew_group_members_created_at", table_name="crew_group_members")
    op.drop_index("ix_crew_group_members_employee_id", table_name="crew_group_members")
    op.drop_index("ix_crew_group_members_crew_group_id", table_name="crew_group_members")
    op.drop_index("ix_crew_group_members_company_id", table_name="crew_group_members")
    op.drop_table("crew_group_members")

    op.drop_index("ix_crew_groups_created_at", table_name="crew_groups")
    op.drop_index("ix_crew_groups_name", table_name="crew_groups")
    op.drop_index("ix_crew_groups_company_id", table_name="crew_groups")
    op.drop_table("crew_groups")

    op.drop_index("ix_jobs_address_label", table_name="jobs")
    op.drop_column("jobs", "address_label")
