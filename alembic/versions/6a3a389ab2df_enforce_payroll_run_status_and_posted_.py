"""enforce payroll_run status and posted_at checks

Revision ID: 6a3a389ab2df
Revises: a2037c8fcb0f
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "6a3a389ab2df"
down_revision: Union[str, Sequence[str], None] = "a2037c8fcb0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allowed statuses (minimal set currently used + needed)
    op.create_check_constraint(
        "ck_payroll_run_status_valid",
        "payroll_run",
        "status in ('DRAFT','POSTED')",
    )

    # posted_at consistency:
    # - POSTED must have posted_at
    # - DRAFT must NOT have posted_at
    op.create_check_constraint(
        "ck_payroll_run_posted_at_consistent",
        "payroll_run",
        "(status = 'POSTED' AND posted_at IS NOT NULL) OR (status = 'DRAFT' AND posted_at IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payroll_run_posted_at_consistent", "payroll_run", type_="check")
    op.drop_constraint("ck_payroll_run_status_valid", "payroll_run", type_="check")
