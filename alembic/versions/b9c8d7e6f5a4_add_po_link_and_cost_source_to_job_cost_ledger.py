"""add po link and cost_source to job_cost_ledger

Revision ID: b9c8d7e6f5a4
Revises: a1b2c3d4e5f7
Create Date: 2026-03-06 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9c8d7e6f5a4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_job_purchase_orders_company_po_id",
        "job_purchase_orders",
        ["company_id", "job_purchase_order_id"],
    )

    op.add_column(
        "job_cost_ledger",
        sa.Column("job_purchase_order_id", sa.String(), nullable=True),
    )
    op.add_column(
        "job_cost_ledger",
        sa.Column("cost_source", sa.String(), server_default="PAYROLL", nullable=False),
    )

    op.create_index(
        "ix_job_cost_ledger_job_purchase_order_id",
        "job_cost_ledger",
        ["job_purchase_order_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_cost_ledger_cost_source",
        "job_cost_ledger",
        ["cost_source"],
        unique=False,
    )

    op.create_check_constraint(
        "ck_job_cost_ledger_cost_source_valid",
        "job_cost_ledger",
        "cost_source IN ('PAYROLL','PO','MANUAL')",
    )
    op.create_check_constraint(
        "ck_job_cost_ledger_po_reference_consistent",
        "job_cost_ledger",
        "(cost_source = 'PO' AND job_purchase_order_id IS NOT NULL) OR "
        "(cost_source IN ('PAYROLL','MANUAL') AND job_purchase_order_id IS NULL)",
    )

    op.create_foreign_key(
        "fk_jcl_company_po_id_job_purchase_orders",
        "job_cost_ledger",
        "job_purchase_orders",
        ["company_id", "job_purchase_order_id"],
        ["company_id", "job_purchase_order_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_jcl_company_po_id_job_purchase_orders",
        "job_cost_ledger",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_job_cost_ledger_po_reference_consistent",
        "job_cost_ledger",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_cost_ledger_cost_source_valid",
        "job_cost_ledger",
        type_="check",
    )

    op.drop_index("ix_job_cost_ledger_cost_source", table_name="job_cost_ledger")
    op.drop_index("ix_job_cost_ledger_job_purchase_order_id", table_name="job_cost_ledger")

    op.drop_column("job_cost_ledger", "cost_source")
    op.drop_column("job_cost_ledger", "job_purchase_order_id")

    op.drop_constraint(
        "uq_job_purchase_orders_company_po_id",
        "job_purchase_orders",
        type_="unique",
    )
