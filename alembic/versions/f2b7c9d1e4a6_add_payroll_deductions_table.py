"""add payroll_deductions table

Revision ID: f2b7c9d1e4a6
Revises: e1f6a9b3c4d5
Create Date: 2026-03-06 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2b7c9d1e4a6"
down_revision: Union[str, Sequence[str], None] = "e1f6a9b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_deductions",
        sa.Column("deduction_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("payroll_run_id", sa.String(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("paystub_id", sa.String(), nullable=True),
        sa.Column("deduction_type", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount_cents >= 0", name="ck_payroll_deductions_amount_cents_nonnegative"),
        sa.ForeignKeyConstraint(
            ["payroll_run_id"],
            ["payroll_run.payroll_run_id"],
            ondelete="RESTRICT",
            name="fk_payroll_deductions_payroll_run_id_payroll_run",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
            name="fk_payroll_deductions_employee_id_employees",
        ),
        sa.ForeignKeyConstraint(
            ["paystub_id"],
            ["paystubs.paystub_id"],
            ondelete="RESTRICT",
            name="fk_payroll_deductions_paystub_id_paystubs",
        ),
        sa.PrimaryKeyConstraint("deduction_id"),
    )

    op.create_index("ix_payroll_deductions_company_id", "payroll_deductions", ["company_id"], unique=False)
    op.create_index("ix_payroll_deductions_payroll_run_id", "payroll_deductions", ["payroll_run_id"], unique=False)
    op.create_index("ix_payroll_deductions_employee_id", "payroll_deductions", ["employee_id"], unique=False)
    op.create_index("ix_payroll_deductions_paystub_id", "payroll_deductions", ["paystub_id"], unique=False)
    op.create_index("ix_payroll_deductions_deduction_type", "payroll_deductions", ["deduction_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payroll_deductions_deduction_type", table_name="payroll_deductions")
    op.drop_index("ix_payroll_deductions_paystub_id", table_name="payroll_deductions")
    op.drop_index("ix_payroll_deductions_employee_id", table_name="payroll_deductions")
    op.drop_index("ix_payroll_deductions_payroll_run_id", table_name="payroll_deductions")
    op.drop_index("ix_payroll_deductions_company_id", table_name="payroll_deductions")
    op.drop_table("payroll_deductions")
