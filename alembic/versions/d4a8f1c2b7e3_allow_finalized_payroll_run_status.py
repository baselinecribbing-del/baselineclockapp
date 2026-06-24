"""allow FINALIZED payroll_run status

Revision ID: d4a8f1c2b7e3
Revises: c91d2e3f4a5b
Create Date: 2026-03-06 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4a8f1c2b7e3"
down_revision: Union[str, Sequence[str], None] = "c91d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_payroll_run_posted_at_consistent", "payroll_run", type_="check")
    op.drop_constraint("ck_payroll_run_status_valid", "payroll_run", type_="check")

    op.create_check_constraint(
        "ck_payroll_run_status_valid",
        "payroll_run",
        "status in ('DRAFT','FINALIZED','POSTED')",
    )

    op.create_check_constraint(
        "ck_payroll_run_posted_at_consistent",
        "payroll_run",
        "(status = 'POSTED' AND posted_at IS NOT NULL) OR "
        "(status IN ('DRAFT','FINALIZED') AND posted_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payroll_run_posted_at_consistent", "payroll_run", type_="check")
    op.drop_constraint("ck_payroll_run_status_valid", "payroll_run", type_="check")

    op.create_check_constraint(
        "ck_payroll_run_status_valid",
        "payroll_run",
        "status in ('DRAFT','POSTED')",
    )

    op.create_check_constraint(
        "ck_payroll_run_posted_at_consistent",
        "payroll_run",
        "(status = 'POSTED' AND posted_at IS NOT NULL) OR (status = 'DRAFT' AND posted_at IS NULL)",
    )
