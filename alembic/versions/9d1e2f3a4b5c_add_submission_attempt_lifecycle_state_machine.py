"""add submission attempt lifecycle state machine

Revision ID: 9d1e2f3a4b5c
Revises: 8c9d0e1f2a3b
Create Date: 2026-03-15 17:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d1e2f3a4b5c"
down_revision: Union[str, Sequence[str], None] = "8c9d0e1f2a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_t4_submission_attempts",
        sa.Column("lifecycle_state", sa.String(), nullable=True, server_default="CREATED"),
    )
    op.add_column(
        "payroll_t4_submission_attempts",
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_attempts",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_attempts",
        sa.Column("failure_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE payroll_t4_submission_attempts AS attempt
        SET
            lifecycle_state = CASE
                WHEN job.status = 'RESPONSE_ACCEPTED_MANUAL' THEN 'RESPONSE_ACCEPTED'
                WHEN job.status = 'RESPONSE_REJECTED_MANUAL' THEN 'RESPONSE_REJECTED'
                WHEN job.status = 'FAILED_MANUAL' THEN 'FAILURE_RECORDED'
                WHEN job.transmission_completed_at IS NOT NULL THEN 'TRANSMISSION_RECORDED'
                WHEN job.queued_at IS NOT NULL THEN 'QUEUED'
                WHEN attempt.validation_passed THEN 'VALIDATED'
                ELSE 'CREATED'
            END,
            validated_at = CASE
                WHEN attempt.validation_passed THEN job.validated_at
                ELSE NULL
            END,
            queued_at = COALESCE(job.queued_at, job.transmission_completed_at, job.response_recorded_at),
            failure_recorded_at = CASE
                WHEN job.status = 'FAILED_MANUAL' THEN COALESCE(job.transmission_completed_at, job.created_at)
                ELSE NULL
            END
        FROM payroll_t4_submission_jobs AS job
        WHERE job.id = attempt.submission_job_id
        """
    )

    op.alter_column("payroll_t4_submission_attempts", "lifecycle_state", nullable=False, server_default="CREATED")
    op.create_check_constraint(
        "ck_payroll_t4_submission_attempts_lifecycle_state_valid",
        "payroll_t4_submission_attempts",
        "lifecycle_state IN ("
        "'CREATED', "
        "'VALIDATED', "
        "'QUEUED', "
        "'TRANSMISSION_RECORDED', "
        "'RESPONSE_ACCEPTED', "
        "'RESPONSE_REJECTED', "
        "'FAILURE_RECORDED'"
        ")",
    )
    op.create_check_constraint(
        "ck_payroll_t4_sub_attempts_lifecycle_fields_complete",
        "payroll_t4_submission_attempts",
        "("
        "lifecycle_state = 'CREATED' "
        "AND validated_at IS NULL AND queued_at IS NULL "
        "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
        "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'VALIDATED' "
        "AND validated_at IS NOT NULL AND queued_at IS NULL "
        "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
        "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'QUEUED' "
        "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
        "AND transmission_recorded_at IS NULL AND response_recorded_at IS NULL "
        "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'TRANSMISSION_RECORDED' "
        "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
        "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NULL "
        "AND failure_recorded_at IS NULL AND response_outcome IS NULL AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'RESPONSE_ACCEPTED' "
        "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
        "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NOT NULL "
        "AND failure_recorded_at IS NULL AND response_outcome = 'ACCEPTED' AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'RESPONSE_REJECTED' "
        "AND validated_at IS NOT NULL AND queued_at IS NOT NULL "
        "AND transmission_recorded_at IS NOT NULL AND response_recorded_at IS NOT NULL "
        "AND failure_recorded_at IS NULL AND response_outcome = 'REJECTED' AND failure_reason IS NULL"
        ") OR ("
        "lifecycle_state = 'FAILURE_RECORDED' "
        "AND validated_at IS NOT NULL "
        "AND failure_recorded_at IS NOT NULL "
        "AND response_recorded_at IS NULL "
        "AND response_outcome = 'FAILED_MANUAL' "
        "AND NULLIF(btrim(COALESCE(failure_reason, '')), '') IS NOT NULL"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_sub_attempts_lifecycle_fields_complete",
        "payroll_t4_submission_attempts",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_t4_submission_attempts_lifecycle_state_valid",
        "payroll_t4_submission_attempts",
        type_="check",
    )
    op.drop_column("payroll_t4_submission_attempts", "failure_recorded_at")
    op.drop_column("payroll_t4_submission_attempts", "queued_at")
    op.drop_column("payroll_t4_submission_attempts", "validated_at")
    op.drop_column("payroll_t4_submission_attempts", "lifecycle_state")
