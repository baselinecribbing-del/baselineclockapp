"""add payroll t4 slip artifact fields

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-03-13 14:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_t4s", sa.Column("slip_file_name", sa.String(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_content_type", sa.String(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_blob", sa.LargeBinary(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_byte_size", sa.Integer(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_sha256", sa.String(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_generated_by_user_id", sa.String(), nullable=True))
    op.add_column(
        "payroll_t4s",
        sa.Column("slip_download_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("payroll_t4s", sa.Column("slip_last_downloaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("slip_last_downloaded_by_user_id", sa.String(), nullable=True))

    op.drop_constraint("ck_payroll_t4s_available_requires_storage_key", "payroll_t4s", type_="check")
    op.create_check_constraint(
        "ck_payroll_t4s_available_requires_artifact",
        "payroll_t4s",
        "(slip_status <> 'AVAILABLE') OR "
        "(slip_storage_key IS NOT NULL AND slip_file_name IS NOT NULL AND slip_content_type IS NOT NULL "
        "AND slip_blob IS NOT NULL AND slip_byte_size IS NOT NULL AND slip_sha256 IS NOT NULL "
        "AND slip_generated_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payroll_t4s_available_requires_artifact", "payroll_t4s", type_="check")
    op.create_check_constraint(
        "ck_payroll_t4s_available_requires_storage_key",
        "payroll_t4s",
        "(slip_status <> 'AVAILABLE') OR (slip_storage_key IS NOT NULL)",
    )
    op.drop_column("payroll_t4s", "slip_last_downloaded_by_user_id")
    op.drop_column("payroll_t4s", "slip_last_downloaded_at")
    op.drop_column("payroll_t4s", "slip_download_count")
    op.drop_column("payroll_t4s", "slip_generated_by_user_id")
    op.drop_column("payroll_t4s", "slip_generated_at")
    op.drop_column("payroll_t4s", "slip_sha256")
    op.drop_column("payroll_t4s", "slip_byte_size")
    op.drop_column("payroll_t4s", "slip_blob")
    op.drop_column("payroll_t4s", "slip_content_type")
    op.drop_column("payroll_t4s", "slip_file_name")
