"""add payroll t4 submission job validation snapshot

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-03-14 03:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3c4d5e6f7a8b"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validation_validator_id", sa.String(), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validation_validator_version", sa.String(), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validation_mode", sa.String(), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validation_status", sa.String(), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("validated_by_user_id", sa.String(), nullable=True),
    )

    op.execute(
        """
        UPDATE payroll_t4_submission_jobs AS job
        SET
            validation_validator_id = artifact.xml_validation_validator_id,
            validation_validator_version = artifact.xml_validation_validator_version,
            validation_mode = artifact.xml_validation_mode,
            validation_status = artifact.xml_validation_status,
            validated_at = artifact.xml_validated_at,
            validated_by_user_id = artifact.xml_validated_by_user_id
        FROM payroll_t4_filing_artifacts AS artifact
        WHERE artifact.filing_artifact_id = job.filing_artifact_id
        """
    )

    op.alter_column("payroll_t4_submission_jobs", "validation_validator_id", nullable=False)
    op.alter_column("payroll_t4_submission_jobs", "validation_validator_version", nullable=False)
    op.alter_column("payroll_t4_submission_jobs", "validation_mode", nullable=False)
    op.alter_column("payroll_t4_submission_jobs", "validation_status", nullable=False)
    op.alter_column("payroll_t4_submission_jobs", "validated_at", nullable=False)

    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_validation_mode_valid",
        "payroll_t4_submission_jobs",
        "validation_mode IN ('INTERNAL_ONLY')",
    )
    op.create_check_constraint(
        "ck_payroll_t4_submission_jobs_validation_status_valid",
        "payroll_t4_submission_jobs",
        "validation_status IN ('VALID')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_validation_status_valid",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_t4_submission_jobs_validation_mode_valid",
        "payroll_t4_submission_jobs",
        type_="check",
    )
    op.drop_column("payroll_t4_submission_jobs", "validated_by_user_id")
    op.drop_column("payroll_t4_submission_jobs", "validated_at")
    op.drop_column("payroll_t4_submission_jobs", "validation_status")
    op.drop_column("payroll_t4_submission_jobs", "validation_mode")
    op.drop_column("payroll_t4_submission_jobs", "validation_validator_version")
    op.drop_column("payroll_t4_submission_jobs", "validation_validator_id")
