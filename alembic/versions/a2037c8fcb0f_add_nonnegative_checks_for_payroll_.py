"""add nonnegative checks for payroll_items and job_cost_ledger

Revision ID: a2037c8fcb0f
Revises: cca694ca74ad
Create Date: 2026-02-26 15:56:43.416769

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2037c8fcb0f"
down_revision: Union[str, Sequence[str], None] = "cca694ca74ad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # payroll_items checks
    op.create_check_constraint(
        "ck_payroll_items_gross_pay_cents_nonnegative",
        "payroll_items",
        "gross_pay_cents >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_items_rate_cents_nonnegative",
        "payroll_items",
        "rate_cents IS NULL OR rate_cents >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_items_hours_nonnegative",
        "payroll_items",
        "hours IS NULL OR hours >= 0",
    )

    # job_cost_ledger checks
    op.create_check_constraint(
        "ck_job_cost_ledger_total_cost_cents_nonnegative",
        "job_cost_ledger",
        "total_cost_cents >= 0",
    )
    op.create_check_constraint(
        "ck_job_cost_ledger_unit_cost_cents_nonnegative",
        "job_cost_ledger",
        "unit_cost_cents IS NULL OR unit_cost_cents >= 0",
    )
    op.create_check_constraint(
        "ck_job_cost_ledger_quantity_nonnegative",
        "job_cost_ledger",
        "quantity IS NULL OR quantity >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # job_cost_ledger checks
    op.drop_constraint(
        "ck_job_cost_ledger_quantity_nonnegative",
        "job_cost_ledger",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_cost_ledger_unit_cost_cents_nonnegative",
        "job_cost_ledger",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_cost_ledger_total_cost_cents_nonnegative",
        "job_cost_ledger",
        type_="check",
    )

    # payroll_items checks
    op.drop_constraint(
        "ck_payroll_items_hours_nonnegative",
        "payroll_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_items_rate_cents_nonnegative",
        "payroll_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_items_gross_pay_cents_nonnegative",
        "payroll_items",
        type_="check",
    )
