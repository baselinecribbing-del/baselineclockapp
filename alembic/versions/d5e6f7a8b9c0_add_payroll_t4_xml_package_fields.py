"""add payroll t4 xml package fields

Revision ID: d5e6f7a8b9c0
Revises: c4e5f6a7b8c9
Create Date: 2026-03-14 00:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_schema_id", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_schema_version", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_storage_key", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_file_name", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_content_type", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_blob", sa.LargeBinary(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_byte_size", sa.Integer(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_package_sha256", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_generated_by_user_id", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_payroll_t4_filing_artifacts_xml_byte_size_nonnegative",
        "payroll_t4_filing_artifacts",
        "xml_package_byte_size IS NULL OR xml_package_byte_size >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_t4_filing_artifacts_xml_package_complete",
        "payroll_t4_filing_artifacts",
        "("
        "xml_package_schema_id IS NULL AND xml_package_schema_version IS NULL "
        "AND xml_package_storage_key IS NULL AND xml_package_file_name IS NULL "
        "AND xml_package_content_type IS NULL AND xml_package_blob IS NULL "
        "AND xml_package_byte_size IS NULL AND xml_package_sha256 IS NULL "
        "AND xml_generated_at IS NULL AND xml_generated_by_user_id IS NULL"
        ") OR ("
        "xml_package_schema_id IS NOT NULL AND xml_package_schema_version IS NOT NULL "
        "AND xml_package_storage_key IS NOT NULL AND xml_package_file_name IS NOT NULL "
        "AND xml_package_content_type IS NOT NULL AND xml_package_blob IS NOT NULL "
        "AND xml_package_byte_size IS NOT NULL AND xml_package_sha256 IS NOT NULL "
        "AND xml_generated_at IS NOT NULL AND xml_generated_by_user_id IS NOT NULL"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_filing_artifacts_xml_package_complete",
        "payroll_t4_filing_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_t4_filing_artifacts_xml_byte_size_nonnegative",
        "payroll_t4_filing_artifacts",
        type_="check",
    )
    op.drop_column("payroll_t4_filing_artifacts", "xml_generated_by_user_id")
    op.drop_column("payroll_t4_filing_artifacts", "xml_generated_at")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_sha256")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_byte_size")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_blob")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_content_type")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_file_name")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_storage_key")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_schema_version")
    op.drop_column("payroll_t4_filing_artifacts", "xml_package_schema_id")
