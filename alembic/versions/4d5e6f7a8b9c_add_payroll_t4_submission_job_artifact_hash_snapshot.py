"""add payroll t4 submission job artifact hash snapshot

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-03-14 03:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4d5e6f7a8b9c"
down_revision: Union[str, Sequence[str], None] = "3c4d5e6f7a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payroll_t4_submission_jobs",
        sa.Column("filing_artifact_sha256", sa.String(), nullable=True),
    )
    op.execute(
        """
        UPDATE payroll_t4_submission_jobs AS job
        SET filing_artifact_sha256 = artifact.artifact_sha256
        FROM payroll_t4_filing_artifacts AS artifact
        WHERE artifact.filing_artifact_id = job.filing_artifact_id
        """
    )
    op.alter_column("payroll_t4_submission_jobs", "filing_artifact_sha256", nullable=False)


def downgrade() -> None:
    op.drop_column("payroll_t4_submission_jobs", "filing_artifact_sha256")
