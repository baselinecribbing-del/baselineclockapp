"""add payroll t4 filing artifacts

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a7
Create Date: 2026-03-13 19:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_t4_filing_artifacts",
        sa.Column("filing_artifact_id", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("filing_status", sa.String(), nullable=False),
        sa.Column("prepared_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_storage_key", sa.String(), nullable=False),
        sa.Column("artifact_file_name", sa.String(), nullable=False),
        sa.Column("artifact_content_type", sa.String(), nullable=False),
        sa.Column("artifact_blob", sa.LargeBinary(), nullable=False),
        sa.Column("artifact_byte_size", sa.Integer(), nullable=False),
        sa.Column("artifact_sha256", sa.String(), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("prepared_by_user_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("filing_artifact_id"),
        sa.UniqueConstraint("company_id", "tax_year", name="uq_payroll_t4_filing_artifacts_company_tax_year"),
        sa.CheckConstraint("tax_year >= 2000", name="ck_payroll_t4_filing_artifacts_tax_year_min"),
        sa.CheckConstraint(
            "filing_status IN ('FILING_ARTIFACT_READY', 'FILING_ARTIFACT_BLOCKED')",
            name="ck_payroll_t4_filing_artifacts_status_valid",
        ),
        sa.CheckConstraint(
            "artifact_byte_size >= 0",
            name="ck_payroll_t4_filing_artifacts_byte_size_nonnegative",
        ),
        sa.CheckConstraint(
            "artifact_storage_key IS NOT NULL AND artifact_file_name IS NOT NULL AND artifact_content_type IS NOT NULL "
            "AND artifact_blob IS NOT NULL AND artifact_byte_size IS NOT NULL AND artifact_sha256 IS NOT NULL",
            name="ck_payroll_t4_filing_artifacts_artifact_complete",
        ),
    )
    op.create_index("ix_payroll_t4_filing_artifacts_company_id", "payroll_t4_filing_artifacts", ["company_id"], unique=False)
    op.create_index("ix_payroll_t4_filing_artifacts_tax_year", "payroll_t4_filing_artifacts", ["tax_year"], unique=False)
    op.create_index(
        "ix_payroll_t4_filing_artifacts_filing_status",
        "payroll_t4_filing_artifacts",
        ["filing_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_t4_filing_artifacts_filing_status", table_name="payroll_t4_filing_artifacts")
    op.drop_index("ix_payroll_t4_filing_artifacts_tax_year", table_name="payroll_t4_filing_artifacts")
    op.drop_index("ix_payroll_t4_filing_artifacts_company_id", table_name="payroll_t4_filing_artifacts")
    op.drop_table("payroll_t4_filing_artifacts")
