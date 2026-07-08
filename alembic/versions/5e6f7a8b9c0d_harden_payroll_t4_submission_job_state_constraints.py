"""harden payroll t4 submission job state constraints

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-03-14 04:20:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "5e6f7a8b9c0d"
down_revision: Union[str, Sequence[str], None] = "4d5e6f7a8b9c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_manual_record_complete",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_manual_record_complete",
        "payroll_t4_submission_jobs",
        "("
        "status = 'PREPARED' AND transmission_started_at IS NULL "
        "AND transmission_completed_at IS NULL AND transmission_reference IS NULL"
        ") OR ("
        "status = 'TRANSMISSION_RECORDED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_manual_record_complete",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_manual_record_complete",
        "payroll_t4_submission_jobs",
        "(status <> 'TRANSMISSION_RECORDED_MANUAL') OR "
        "(transmission_started_at IS NOT NULL AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL)",
    )
