"""add crews and crew members

Revision ID: fc1a2b3d4e5f
Revises: fab4e1c2d9a7
Create Date: 2026-03-08 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fc1a2b3d4e5f"
down_revision: Union[str, Sequence[str], None] = "fab4e1c2d9a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crews",
        sa.Column("crew_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("supervisor_employee_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["supervisor_employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("crew_id"),
    )
    op.create_index("ix_crews_company_id", "crews", ["company_id"], unique=False)
    op.create_index("ix_crews_name", "crews", ["name"], unique=False)
    op.create_index("ix_crews_supervisor_employee_id", "crews", ["supervisor_employee_id"], unique=False)
    op.create_index("ix_crews_is_active", "crews", ["is_active"], unique=False)

    op.create_table(
        "crew_members",
        sa.Column("crew_member_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("crew_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.crew_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("crew_member_id"),
    )
    op.create_index("ix_crew_members_company_id", "crew_members", ["company_id"], unique=False)
    op.create_index("ix_crew_members_crew_id", "crew_members", ["crew_id"], unique=False)
    op.create_index("ix_crew_members_employee_id", "crew_members", ["employee_id"], unique=False)
    op.create_index("ix_crew_members_assigned_at", "crew_members", ["assigned_at"], unique=False)
    op.create_index("ix_crew_members_removed_at", "crew_members", ["removed_at"], unique=False)

    op.execute(
        "CREATE UNIQUE INDEX uq_crew_members_active_company_crew_employee "
        "ON crew_members (company_id, crew_id, employee_id) "
        "WHERE removed_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_crew_members_active_company_crew_employee")

    op.drop_index("ix_crew_members_removed_at", table_name="crew_members")
    op.drop_index("ix_crew_members_assigned_at", table_name="crew_members")
    op.drop_index("ix_crew_members_employee_id", table_name="crew_members")
    op.drop_index("ix_crew_members_crew_id", table_name="crew_members")
    op.drop_index("ix_crew_members_company_id", table_name="crew_members")
    op.drop_table("crew_members")

    op.drop_index("ix_crews_is_active", table_name="crews")
    op.drop_index("ix_crews_supervisor_employee_id", table_name="crews")
    op.drop_index("ix_crews_name", table_name="crews")
    op.drop_index("ix_crews_company_id", table_name="crews")
    op.drop_table("crews")
