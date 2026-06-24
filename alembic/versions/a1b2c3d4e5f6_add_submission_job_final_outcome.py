"""add submission job final outcome

Revision ID: a1b2c3d4e5f6
Revises: 9d1e2f3a4b5c
Create Date: 2026-03-15 19:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9d1e2f3a4b5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("final_outcome", sa.String(), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("final_outcome_detail", sa.String(), nullable=True),
    )

    op.execute(
        """
        UPDATE payroll_t4_submission_jobs
        SET
            final_outcome = CASE
                WHEN status = 'RESPONSE_ACCEPTED_MANUAL' THEN 'ACCEPTED'
                WHEN status = 'RESPONSE_REJECTED_MANUAL' THEN 'REJECTED'
                WHEN status = 'FAILED_MANUAL' THEN 'FAILED_MANUAL'
                ELSE NULL
            END,
            final_outcome_detail = CASE
                WHEN status = 'RESPONSE_ACCEPTED_MANUAL' THEN COALESCE(NULLIF(btrim(response_message), ''), NULLIF(btrim(response_reference), ''))
                WHEN status = 'RESPONSE_REJECTED_MANUAL' THEN COALESCE(NULLIF(btrim(response_message), ''), NULLIF(btrim(response_code), ''), NULLIF(btrim(response_reference), ''))
                WHEN status = 'FAILED_MANUAL' THEN COALESCE(NULLIF(btrim(failure_message), ''), NULLIF(btrim(failure_code), ''))
                ELSE NULL
            END
        """
    )

    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_final_outcome_valid",
        "payroll_t4_submission_jobs",
        "final_outcome IS NULL OR final_outcome IN ('ACCEPTED', 'REJECTED', 'FAILED_MANUAL')",
    )

def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_final_outcome_valid",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.drop_column("payroll_t4_submission_jobs", "final_outcome_detail")
    op.drop_column("payroll_t4_submission_jobs", "final_outcome")
