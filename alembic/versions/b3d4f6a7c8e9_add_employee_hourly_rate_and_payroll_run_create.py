"""add employee hourly rate and payroll run create support

Revision ID: b3d4f6a7c8e9
Revises: 9c7e6a1b4d21
Create Date: 2026-03-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d4f6a7c8e9"
down_revision: Union[str, Sequence[str], None] = "9c7e6a1b4d21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("hourly_rate_cents", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_employees_hourly_rate_cents_nonnegative",
        "employees",
        "hourly_rate_cents >= 0",
    )
    op.alter_column("employees", "hourly_rate_cents", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_employees_hourly_rate_cents_nonnegative", "employees", type_="check")
    op.drop_column("employees", "hourly_rate_cents")
