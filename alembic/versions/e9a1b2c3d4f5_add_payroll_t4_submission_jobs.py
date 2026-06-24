"""add payroll t4 submission jobs

Revision ID: e9a1b2c3d4f5
Revises: e6f7a8b9c0d1
Create Date: 2026-03-14 01:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a1b2c3d4f5"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_t4_submission_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("filing_artifact_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PREPARED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_user_id", sa.String(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transmission_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transmission_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transmission_reference", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("failure_message", sa.String(), nullable=True),
        sa.Column("xml_package_sha256", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["filing_artifact_id"],
            ["payroll_t4_filing_artifacts.filing_artifact_id"],
            name="fk_payroll_t4_submission_jobs_filing_artifact_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "tax_year",
            "xml_package_sha256",
            name="uq_payroll_t4_submission_jobs_company_year_xml_hash",
        ),
        sa.CheckConstraint(
            "tax_year >= 2000",
            name="ck_payroll_t4_submission_jobs_tax_year_min",
        ),
        sa.CheckConstraint(
            "status IN ('PREPARED', 'TRANSMISSION_RECORDED_MANUAL')",
            name="ck_payroll_t4_submission_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "(status <> 'TRANSMISSION_RECORDED_MANUAL') OR "
            "(transmission_started_at IS NOT NULL AND transmission_completed_at IS NOT NULL AND transmission_reference IS NOT NULL)",
            name="ck_payroll_t4_submission_jobs_manual_record_complete",
        ),
    )
    op.create_index(
        "ix_payroll_t4_submission_jobs_company_id",
        "payroll_t4_submission_jobs",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_t4_submission_jobs_tax_year",
        "payroll_t4_submission_jobs",
        ["tax_year"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_t4_submission_jobs_filing_artifact_id",
        "payroll_t4_submission_jobs",
        ["filing_artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_payroll_t4_submission_jobs_status",
        "payroll_t4_submission_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payroll_t4_submission_jobs_status", table_name="payroll_t4_submission_jobs")
    op.drop_index("ix_payroll_t4_submission_jobs_filing_artifact_id", table_name="payroll_t4_submission_jobs")
    op.drop_index("ix_payroll_t4_submission_jobs_tax_year", table_name="payroll_t4_submission_jobs")
    op.drop_index("ix_payroll_t4_submission_jobs_company_id", table_name="payroll_t4_submission_jobs")
    op.drop_table("payroll_t4_submission_jobs")
