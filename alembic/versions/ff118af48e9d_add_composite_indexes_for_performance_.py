"""add composite indexes for performance hardening

Revision ID: ff118af48e9d
Revises: 6a3a389ab2df
Create Date: 2026-02-26 20:29:55.044478

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff118af48e9d'
down_revision: Union[str, Sequence[str], None] = '6a3a389ab2df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EventOutbox
    op.create_index(
        "ix_outbox_company_processed_id",
        "event_outbox",
        ["company_id", "processed", "id"],
    )

    op.create_index(
        "ix_outbox_company_processed_retry_created",
        "event_outbox",
        ["company_id", "processed", "retry_count", "created_at"],
    )

    # JobCostLedger
    op.create_index(
        "ix_jcl_company_posting_date",
        "job_cost_ledger",
        ["company_id", "posting_date"],
    )

    op.create_index(
        "ix_jcl_company_source_ref",
        "job_cost_ledger",
        ["company_id", "source_type", "source_reference_id"],
    )

    op.create_index(
        "ix_jcl_company_job_posting",
        "job_cost_ledger",
        ["company_id", "job_id", "posting_date"],
    )

    # PayrollItem
    op.create_index(
        "ix_payroll_items_company_run",
        "payroll_items",
        ["company_id", "payroll_run_id"],
    )

def downgrade() -> None:
    op.drop_index("ix_payroll_items_company_run", table_name="payroll_items")

    op.drop_index("ix_jcl_company_job_posting", table_name="job_cost_ledger")
    op.drop_index("ix_jcl_company_source_ref", table_name="job_cost_ledger")
    op.drop_index("ix_jcl_company_posting_date", table_name="job_cost_ledger")

    op.drop_index("ix_outbox_company_processed_retry_created", table_name="event_outbox")
    op.drop_index("ix_outbox_company_processed_id", table_name="event_outbox")
