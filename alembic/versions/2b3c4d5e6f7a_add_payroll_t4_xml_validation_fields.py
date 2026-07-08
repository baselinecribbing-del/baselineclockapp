"""add payroll t4 xml validation fields

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-03-14 02:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2b3c4d5e6f7a"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validation_validator_id", sa.String(), nullable=True))
    op.add_column(
        "payroll_t4_filing_artifacts",
        sa.Column("xml_validation_validator_version", sa.String(), nullable=True),
    )
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validation_mode", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validation_status", sa.String(), nullable=True))
    op.add_column(
        "payroll_t4_filing_artifacts",
        sa.Column("xml_validation_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validation_xml_sha256", sa.String(), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4_filing_artifacts", sa.Column("xml_validated_by_user_id", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_complete",
        "payroll_t4_filing_artifacts",
        "("
        "xml_validation_validator_id IS NULL AND xml_validation_validator_version IS NULL "
        "AND xml_validation_mode IS NULL AND xml_validation_status IS NULL "
        "AND xml_validation_result_json IS NULL AND xml_validation_xml_sha256 IS NULL "
        "AND xml_validated_at IS NULL AND xml_validated_by_user_id IS NULL"
        ") OR ("
        "xml_validation_validator_id IS NOT NULL AND xml_validation_validator_version IS NOT NULL "
        "AND xml_validation_mode IS NOT NULL AND xml_validation_status IS NOT NULL "
        "AND xml_validation_result_json IS NOT NULL AND xml_validation_xml_sha256 IS NOT NULL "
        "AND xml_validated_at IS NOT NULL"
        ")",
    )
    op.create_check_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_mode_valid",
        "payroll_t4_filing_artifacts",
        "xml_validation_mode IS NULL OR xml_validation_mode IN ('INTERNAL_ONLY')",
    )
    op.create_check_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_status_valid",
        "payroll_t4_filing_artifacts",
        "xml_validation_status IS NULL OR xml_validation_status IN ('VALID', 'INVALID')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_status_valid",
        "payroll_t4_filing_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_mode_valid",
        "payroll_t4_filing_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "ck_payroll_t4_filing_artifacts_xml_validation_complete",
        "payroll_t4_filing_artifacts",
        type_="check",
    )
    op.drop_column("payroll_t4_filing_artifacts", "xml_validated_by_user_id")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validated_at")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_xml_sha256")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_result_json")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_status")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_mode")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_validator_version")
    op.drop_column("payroll_t4_filing_artifacts", "xml_validation_validator_id")
