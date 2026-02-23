"""add payroll_items table

Revision ID: cca694ca74ad
Revises: 95488ac353c6
Create Date: 2026-02-22 19:40:10.512521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "cca694ca74ad"
down_revision: Union[str, Sequence[str], None] = "95488ac353c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_items",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column(
            "payroll_run_id",
            sa.String(),
            sa.ForeignKey("payroll_run.payroll_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Minimal, forward-compatible fields (can expand later)
        sa.Column("hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("rate_cents", sa.Integer(), nullable=True),
        sa.Column("gross_pay_cents", sa.Integer(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_payroll_items_company_id", "payroll_items", ["company_id"], unique=False)
    op.create_index("ix_payroll_items_payroll_run_id", "payroll_items", ["payroll_run_id"], unique=False)
    op.create_index("ix_payroll_items_employee_id", "payroll_items", ["employee_id"], unique=False)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payroll_items_employee_id")
    op.execute("DROP INDEX IF EXISTS ix_payroll_items_payroll_run_id")
    op.execute("DROP INDEX IF EXISTS ix_payroll_items_company_id")
    op.execute("DROP TABLE IF EXISTS payroll_items")
