"""drop submission job final outcome complete constraint

Revision ID: c9d8e7f6a5b4
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE payroll_t4_submission_jobs "
        "DROP CONSTRAINT IF EXISTS ck_payroll_t4_sub_jobs_final_outcome_complete"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE payroll_t4_submission_jobs "
        "ADD CONSTRAINT ck_payroll_t4_sub_jobs_final_outcome_complete "
        "CHECK (("
        "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL') "
        "AND final_outcome IS NULL AND final_outcome_detail IS NULL"
        ") OR ("
        "status = 'FAILED_MANUAL' "
        "AND final_outcome = 'FAILED_MANUAL' "
        "AND NULLIF(btrim(COALESCE(final_outcome_detail, '')), '') IS NOT NULL"
        ") OR ("
        "status = 'RESPONSE_ACCEPTED_MANUAL' "
        "AND final_outcome = 'ACCEPTED' "
        "AND NULLIF(btrim(COALESCE(final_outcome_detail, '')), '') IS NOT NULL"
        ") OR ("
        "status = 'RESPONSE_REJECTED_MANUAL' "
        "AND final_outcome = 'REJECTED' "
        "AND NULLIF(btrim(COALESCE(final_outcome_detail, '')), '') IS NOT NULL"
        "))"
    )
