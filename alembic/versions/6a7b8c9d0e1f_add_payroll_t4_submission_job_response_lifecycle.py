"""add payroll t4 submission job response lifecycle

Revision ID: 6a7b8c9d0e1f
Revises: 5e6f7a8b9c0d
Create Date: 2026-03-14 06:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, Sequence[str], None] = "5e6f7a8b9c0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_status", sa.String(), nullable=True))
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_recorded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_recorded_by_user_id", sa.String(), nullable=True))
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_reference", sa.String(), nullable=True))
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_code", sa.String(), nullable=True))
    op.add_column("payroll_t4_submission_jobs", sa.Column("response_message", sa.String(), nullable=True))

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

    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_response_status_valid",
        "payroll_t4_submission_jobs",
        "response_status IS NULL OR response_status IN ('ACCEPTED', 'REJECTED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_response_status_valid",
        "payroll_t4_submission_jobs",
        type_="check",
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
        "AND transmission_completed_at IS NULL AND transmission_reference IS NULL"
        ") OR ("
        "status = 'TRANSMISSION_RECORDED_MANUAL' AND transmission_started_at IS NOT NULL "
        "AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL "
        "AND transmission_completed_at >= transmission_started_at"
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
        "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL')",
    )

    op.drop_column("payroll_t4_submission_jobs", "response_message")
    op.drop_column("payroll_t4_submission_jobs", "response_code")
    op.drop_column("payroll_t4_submission_jobs", "response_reference")
    op.drop_column("payroll_t4_submission_jobs", "response_recorded_by_user_id")
    op.drop_column("payroll_t4_submission_jobs", "response_recorded_at")
    op.drop_column("payroll_t4_submission_jobs", "response_status")
