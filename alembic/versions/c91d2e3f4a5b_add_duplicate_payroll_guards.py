"""add duplicate payroll guards

Revision ID: c91d2e3f4a5b
Revises: b3d4f6a7c8e9
Create Date: 2026-03-06 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c91d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "b3d4f6a7c8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_items",
        sa.Column("source_time_entry_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_payroll_items_source_time_entry_id_time_entries",
        "payroll_items",
        "time_entries",
        ["source_time_entry_id"],
        ["time_entry_id"],
    )
    op.create_unique_constraint(
        "uq_payroll_items_company_id_source_time_entry_id",
        "payroll_items",
        ["company_id", "source_time_entry_id"],
    )
    op.create_unique_constraint(
        "uq_payroll_runs_company_id_pay_period_id",
        "payroll_run",
        ["company_id", "pay_period_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payroll_runs_company_id_pay_period_id", "payroll_run", type_="unique")
    op.drop_constraint("uq_payroll_items_company_id_source_time_entry_id", "payroll_items", type_="unique")
    op.drop_constraint(
        "fk_payroll_items_source_time_entry_id_time_entries",
        "payroll_items",
        type_="foreignkey",
    )
    op.drop_column("payroll_items", "source_time_entry_id")
