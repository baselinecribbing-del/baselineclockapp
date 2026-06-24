"""add payroll t4 distribution lifecycle

Revision ID: f8c1d2e3a4b5
Revises: f7a8b9c0d1e2
Create Date: 2026-03-13 16:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8c1d2e3a4b5"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payroll_t4s", sa.Column("slip_available_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "payroll_t4s",
        sa.Column("delivery_status", sa.String(), nullable=False, server_default="PENDING_MANUAL"),
    )
    op.add_column("payroll_t4s", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("delivered_by_user_id", sa.String(), nullable=True))
    op.add_column(
        "payroll_t4s",
        sa.Column("employee_download_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("payroll_t4s", sa.Column("employee_first_downloaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("employee_last_downloaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("employee_last_downloaded_by_user_id", sa.String(), nullable=True))
    op.add_column("payroll_t4s", sa.Column("employee_acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_t4s", sa.Column("employee_acknowledged_by_user_id", sa.String(), nullable=True))

    op.execute(
        "UPDATE payroll_t4s "
        "SET slip_available_at = slip_generated_at "
        "WHERE slip_status = 'AVAILABLE' AND slip_generated_at IS NOT NULL"
    )

    op.create_index("ix_payroll_t4s_delivery_status", "payroll_t4s", ["delivery_status"], unique=False)

    op.drop_constraint("ck_payroll_t4s_available_requires_artifact", "payroll_t4s", type_="check")
    op.create_check_constraint(
        "ck_payroll_t4s_available_requires_artifact",
        "payroll_t4s",
        "(slip_status <> 'AVAILABLE') OR "
        "(slip_storage_key IS NOT NULL AND slip_file_name IS NOT NULL AND slip_content_type IS NOT NULL "
        "AND slip_blob IS NOT NULL AND slip_byte_size IS NOT NULL AND slip_sha256 IS NOT NULL "
        "AND slip_generated_at IS NOT NULL AND slip_available_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_payroll_t4s_delivery_status_valid",
        "payroll_t4s",
        "delivery_status IN ('PENDING_MANUAL', 'DELIVERED_MANUAL')",
    )
    op.create_check_constraint(
        "ck_payroll_t4s_delivery_state_consistent",
        "payroll_t4s",
        "(delivery_status = 'PENDING_MANUAL' AND delivered_at IS NULL AND delivered_by_user_id IS NULL) OR "
        "(delivery_status = 'DELIVERED_MANUAL' AND delivered_at IS NOT NULL AND delivered_by_user_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_payroll_t4s_slip_download_count_nonnegative",
        "payroll_t4s",
        "slip_download_count >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_t4s_employee_download_count_nonnegative",
        "payroll_t4s",
        "employee_download_count >= 0",
    )
    op.create_check_constraint(
        "ck_payroll_t4s_employee_ack_state_consistent",
        "payroll_t4s",
        "(employee_acknowledged_at IS NULL AND employee_acknowledged_by_user_id IS NULL) OR "
        "(employee_acknowledged_at IS NOT NULL AND employee_acknowledged_by_user_id IS NOT NULL)",
    )

    op.alter_column("payroll_t4s", "delivery_status", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_payroll_t4s_employee_ack_state_consistent", "payroll_t4s", type_="check")
    op.drop_constraint("ck_payroll_t4s_employee_download_count_nonnegative", "payroll_t4s", type_="check")
    op.drop_constraint("ck_payroll_t4s_slip_download_count_nonnegative", "payroll_t4s", type_="check")
    op.drop_constraint("ck_payroll_t4s_delivery_state_consistent", "payroll_t4s", type_="check")
    op.drop_constraint("ck_payroll_t4s_delivery_status_valid", "payroll_t4s", type_="check")
    op.drop_constraint("ck_payroll_t4s_available_requires_artifact", "payroll_t4s", type_="check")
    op.create_check_constraint(
        "ck_payroll_t4s_available_requires_artifact",
        "payroll_t4s",
        "(slip_status <> 'AVAILABLE') OR "
        "(slip_storage_key IS NOT NULL AND slip_file_name IS NOT NULL AND slip_content_type IS NOT NULL "
        "AND slip_blob IS NOT NULL AND slip_byte_size IS NOT NULL AND slip_sha256 IS NOT NULL "
        "AND slip_generated_at IS NOT NULL)",
    )
    op.drop_index("ix_payroll_t4s_delivery_status", table_name="payroll_t4s")
    op.drop_column("payroll_t4s", "employee_acknowledged_by_user_id")
    op.drop_column("payroll_t4s", "employee_acknowledged_at")
    op.drop_column("payroll_t4s", "employee_last_downloaded_by_user_id")
    op.drop_column("payroll_t4s", "employee_last_downloaded_at")
    op.drop_column("payroll_t4s", "employee_first_downloaded_at")
    op.drop_column("payroll_t4s", "employee_download_count")
    op.drop_column("payroll_t4s", "delivered_by_user_id")
    op.drop_column("payroll_t4s", "delivered_at")
    op.drop_column("payroll_t4s", "delivery_status")
    op.drop_column("payroll_t4s", "slip_available_at")
