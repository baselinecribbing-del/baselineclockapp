"""add employee labor classification flags

Revision ID: f9a0b1c2d3e4
Revises: e7f8a9b0c1d2
Create Date: 2026-03-07 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("labor_class", sa.String(), nullable=False, server_default="PAYROLL_EMPLOYEE"),
    )
    op.add_column(
        "employees",
        sa.Column("include_wcb_cost", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "employees",
        sa.Column("include_ei_cost", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "employees",
        sa.Column("include_tax_cost", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "employees",
        sa.Column("requires_payroll", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_check_constraint(
        "ck_employees_labor_class_valid",
        "employees",
        "labor_class IN ('PAYROLL_EMPLOYEE','CASUAL_CASH','SUBCONTRACTOR_HOURLY')",
    )
    op.create_index("ix_employees_labor_class", "employees", ["labor_class"], unique=False)
    op.create_index("ix_employees_requires_payroll", "employees", ["requires_payroll"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_employees_requires_payroll", table_name="employees")
    op.drop_index("ix_employees_labor_class", table_name="employees")
    op.drop_constraint("ck_employees_labor_class_valid", "employees", type_="check")

    op.drop_column("employees", "requires_payroll")
    op.drop_column("employees", "include_tax_cost")
    op.drop_column("employees", "include_ei_cost")
    op.drop_column("employees", "include_wcb_cost")
    op.drop_column("employees", "labor_class")
