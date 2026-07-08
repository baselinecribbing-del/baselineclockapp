"""add unique constraint for payroll_deductions idempotency

Revision ID: b4d9e2a1c6f7
Revises: a7c3d9e2f1b4
Create Date: 2026-03-06 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b4d9e2a1c6f7"
down_revision: Union[str, Sequence[str], None] = "a7c3d9e2f1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_payroll_deductions_company_run_employee_type",
        "payroll_deductions",
        ["company_id", "payroll_run_id", "employee_id", "deduction_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payroll_deductions_company_run_employee_type",
        "payroll_deductions",
        type_="unique",
    )
