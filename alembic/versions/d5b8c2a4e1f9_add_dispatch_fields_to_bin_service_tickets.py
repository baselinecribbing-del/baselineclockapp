"""add dispatch fields to bin service tickets

Revision ID: d5b8c2a4e1f9
Revises: c3f7a1d9b2e4
Create Date: 2026-03-07 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5b8c2a4e1f9"
down_revision: Union[str, Sequence[str], None] = "c3f7a1d9b2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bin_service_tickets", sa.Column("assigned_employee_id", sa.Integer(), nullable=True))
    op.add_column("bin_service_tickets", sa.Column("assigned_vehicle_label", sa.String(), nullable=True))
    op.add_column(
        "bin_service_tickets",
        sa.Column("priority", sa.String(), nullable=False, server_default="NORMAL"),
    )
    op.add_column("bin_service_tickets", sa.Column("scheduled_date", sa.Date(), nullable=True))
    op.add_column("bin_service_tickets", sa.Column("scheduled_time_window", sa.String(), nullable=True))
    op.add_column("bin_service_tickets", sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_bin_service_tickets_assigned_employee_id", "bin_service_tickets", ["assigned_employee_id"], unique=False)
    op.create_index("ix_bin_service_tickets_priority", "bin_service_tickets", ["priority"], unique=False)
    op.create_index("ix_bin_service_tickets_scheduled_date", "bin_service_tickets", ["scheduled_date"], unique=False)

    op.create_foreign_key(
        "fk_bin_service_tickets_assigned_employee",
        "bin_service_tickets",
        "employees",
        ["assigned_employee_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("ck_bin_service_tickets_status_valid", "bin_service_tickets", type_="check")
    op.create_check_constraint(
        "ck_bin_service_tickets_status_valid",
        "bin_service_tickets",
        "status IN ('OPEN','SCHEDULED','DISPATCHED','COMPLETED','CANCELLED')",
    )

    op.create_check_constraint(
        "ck_bin_service_tickets_priority_valid",
        "bin_service_tickets",
        "priority IN ('LOW','NORMAL','HIGH','URGENT')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bin_service_tickets_priority_valid", "bin_service_tickets", type_="check")

    op.drop_constraint("ck_bin_service_tickets_status_valid", "bin_service_tickets", type_="check")
    op.create_check_constraint(
        "ck_bin_service_tickets_status_valid",
        "bin_service_tickets",
        "status IN ('OPEN','SCHEDULED','COMPLETED','CANCELLED')",
    )

    op.drop_constraint("fk_bin_service_tickets_assigned_employee", "bin_service_tickets", type_="foreignkey")

    op.drop_index("ix_bin_service_tickets_scheduled_date", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_priority", table_name="bin_service_tickets")
    op.drop_index("ix_bin_service_tickets_assigned_employee_id", table_name="bin_service_tickets")

    op.drop_column("bin_service_tickets", "dispatched_at")
    op.drop_column("bin_service_tickets", "scheduled_time_window")
    op.drop_column("bin_service_tickets", "scheduled_date")
    op.drop_column("bin_service_tickets", "priority")
    op.drop_column("bin_service_tickets", "assigned_vehicle_label")
    op.drop_column("bin_service_tickets", "assigned_employee_id")
