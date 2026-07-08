"""add payroll t4 submission job manual failure lifecycle

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-03-14 07:05:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "7b8c9d0e1f2a"
down_revision: Union[str, Sequence[str], None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_status_valid",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_status_valid",
        "payroll_t4_submission_jobs",
        "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL', 'FAILED_MANUAL', 'RESPONSE_ACCEPTED_MANUAL', 'RESPONSE_REJECTED_MANUAL')",
    )

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
        "AND transmission_completed_at IS NULL AND transmission_reference IS NULL "
        "AND response_status IS NULL AND response_recorded_at IS NULL "
        "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
        "AND response_code IS NULL AND response_message IS NULL "
        "AND failure_code IS NULL AND failure_message IS NULL"
        ") OR ("
        "status = 'TRANSMISSION_RECORDED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status IS NULL AND response_recorded_at IS NULL "
        "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
        "AND response_code IS NULL AND response_message IS NULL "
        "AND failure_code IS NULL AND failure_message IS NULL"
        ") OR ("
        "status = 'FAILED_MANUAL' AND response_status IS NULL "
        "AND response_recorded_at IS NULL AND response_recorded_by_user_id IS NULL "
        "AND response_reference IS NULL AND response_code IS NULL AND response_message IS NULL "
        "AND (NULLIF(btrim(COALESCE(failure_code, '')), '') IS NOT NULL "
        "OR NULLIF(btrim(COALESCE(failure_message, '')), '') IS NOT NULL)"
        ") OR ("
        "status = 'RESPONSE_ACCEPTED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status = 'ACCEPTED' AND response_recorded_at IS NOT NULL "
        "AND failure_code IS NULL AND failure_message IS NULL"
        ") OR ("
        "status = 'RESPONSE_REJECTED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status = 'REJECTED' AND response_recorded_at IS NOT NULL "
        "AND failure_code IS NULL AND failure_message IS NULL "
        "AND (NULLIF(btrim(COALESCE(response_code, '')), '') IS NOT NULL "
        "OR NULLIF(btrim(COALESCE(response_message, '')), '') IS NOT NULL)"
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
        "("
        "status = 'PREPARED' AND transmission_started_at IS NULL "
        "AND transmission_completed_at IS NULL AND transmission_reference IS NULL "
        "AND response_status IS NULL AND response_recorded_at IS NULL "
        "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
        "AND response_code IS NULL AND response_message IS NULL"
        ") OR ("
        "status = 'TRANSMISSION_RECORDED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status IS NULL AND response_recorded_at IS NULL "
        "AND response_recorded_by_user_id IS NULL AND response_reference IS NULL "
        "AND response_code IS NULL AND response_message IS NULL"
        ") OR ("
        "status = 'RESPONSE_ACCEPTED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status = 'ACCEPTED' AND response_recorded_at IS NOT NULL"
        ") OR ("
        "status = 'RESPONSE_REJECTED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at "
        "AND response_status = 'REJECTED' AND response_recorded_at IS NOT NULL "
        "AND (NULLIF(btrim(COALESCE(response_code, '')), '') IS NOT NULL "
        "OR NULLIF(btrim(COALESCE(response_message, '')), '') IS NOT NULL)"
        ")",
    )

    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_status_valid",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_status_valid",
        "payroll_t4_submission_jobs",
        "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL', 'RESPONSE_ACCEPTED_MANUAL', 'RESPONSE_REJECTED_MANUAL')",
    )
