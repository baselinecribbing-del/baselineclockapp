"""extend job documents for intake job and hazard photos

Revision ID: 7e4a1c2d9b6f
Revises: 6c8f4e2a1b7d
Create Date: 2026-03-10 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7e4a1c2d9b6f"
down_revision: Union[str, Sequence[str], None] = "6c8f4e2a1b7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_documents", sa.Column("job_start_intake_id", sa.String(), nullable=True))
    op.add_column("job_documents", sa.Column("hazard_assessment_id", sa.String(), nullable=True))
    op.add_column("job_documents", sa.Column("caption", sa.Text(), nullable=True))

    op.create_index("ix_job_documents_job_start_intake_id", "job_documents", ["job_start_intake_id"], unique=False)
    op.create_index("ix_job_documents_hazard_assessment_id", "job_documents", ["hazard_assessment_id"], unique=False)

    op.create_foreign_key(
        "fk_job_documents_job_start_intake_id",
        "job_documents",
        "job_start_intakes",
        ["job_start_intake_id"],
        ["job_start_intake_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_job_documents_hazard_assessment_id",
        "job_documents",
        "hazard_assessments",
        ["hazard_assessment_id"],
        ["hazard_assessment_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_job_documents_document_type_valid",
        "job_documents",
        "document_type IN ('BLUEPRINT','GRADE_SLIP','SITE_PLAN','STAKE_DATE','OTHER','ISSUE_PHOTO')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_documents_document_type_valid", "job_documents", type_="check")
    op.drop_constraint("fk_job_documents_hazard_assessment_id", "job_documents", type_="foreignkey")
    op.drop_constraint("fk_job_documents_job_start_intake_id", "job_documents", type_="foreignkey")
    op.drop_index("ix_job_documents_hazard_assessment_id", table_name="job_documents")
    op.drop_index("ix_job_documents_job_start_intake_id", table_name="job_documents")
    op.drop_column("job_documents", "caption")
    op.drop_column("job_documents", "hazard_assessment_id")
    op.drop_column("job_documents", "job_start_intake_id")
