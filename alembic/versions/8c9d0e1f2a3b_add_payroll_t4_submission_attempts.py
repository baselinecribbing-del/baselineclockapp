"""add payroll t4 submission attempts

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-03-15 16:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c9d0e1f2a3b"
down_revision: Union[str, Sequence[str], None] = "7b8c9d0e1f2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_t4_submission_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("submission_job_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("validation_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("transmission_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_outcome", sa.String(), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["submission_job_id"],
            ["payroll_t4_submission_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submission_job_id",
            "attempt_number",
            name="uq_payroll_t4_submission_attempts_job_attempt",
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_payroll_t4_submission_attempts_attempt_number_min",
        ),
        sa.CheckConstraint(
            "response_outcome IS NULL OR response_outcome IN ('ACCEPTED', 'REJECTED', 'FAILED_MANUAL')",
            name="ck_payroll_t4_submission_attempts_response_outcome_valid",
        ),
        sa.CheckConstraint(
            "(response_outcome <> 'FAILED_MANUAL') OR (NULLIF(btrim(COALESCE(failure_reason, '')), '') IS NOT NULL)",
            name="ck_payroll_t4_submission_attempts_failed_reason_required",
        ),
    )
    op.create_index(
        "ix_payroll_t4_submission_attempts_company_id",
        "payroll_t4_submission_attempts",
        ["company_id"],
    )
    op.create_index(
        "ix_payroll_t4_submission_attempts_submission_job_id",
        "payroll_t4_submission_attempts",
        ["submission_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_t4_submission_attempts_submission_job_id", table_name="payroll_t4_submission_attempts")
    op.drop_index("ix_payroll_t4_submission_attempts_company_id", table_name="payroll_t4_submission_attempts")
    op.drop_table("payroll_t4_submission_attempts")
